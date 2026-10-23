"""Versioned topic recommendations from cited relevance and point-in-time prices.

Text establishes a research universe and can veto a signal; it is never converted
into an invented return coefficient. The fixed analogue strategy is evaluated in
chronological order with purged, non-overlapping outcome windows.
"""
from __future__ import annotations
from collections import OrderedDict, defaultdict
import math
import statistics
import threading

from . import analysis as a
from .financial_analysis import _prepare, _prices, _daily_gap, _input, _availability, _currency, PRICE_METRICS
from .storage import dumps, now_ms

MODEL_VERSION = 'topic-analogues-1'
POLICY = {'lookbackSessions': 20, 'horizonSessions': 5, 'minimumTrainingSamples': 30,
          'minimumAnalogues': 20, 'maximumAnalogues': 40, 'minimumValidationSamples': 20,
          'minimumValidationSignals': 10, 'marketMaxAgeHours': 36, 'providerDisagreementPercent': 1, 'maximumHistorySessions': 1500}
DEPENDENCIES = ('source', 'document', 'claim', 'asset', 'observation', 'observationVintage',
                'relationship', 'networkGraph', 'topicPortfolio', 'setting')
BAD_STATES = {'Disputed', 'Contradicted', 'Retracted', 'Misleading', 'Review required'}


def _record(row):
    return {**_input(row), **{k:row[k] for k in ('historicalAvailabilityUnknown','availabilityBasis','adjustedPriceNotExecutable') if k in row}}


def _percentile(values, fraction):
    ordered = sorted(values)
    pos = (len(ordered) - 1) * fraction
    low = math.floor(pos)
    return ordered[low] + (ordered[math.ceil(pos)] - ordered[low]) * (pos - low)


def _features(window):
    returns = [math.log(right['value']) - math.log(left['value']) for left, right in zip(window, window[1:])]
    features = [(window[-1]['value'] / window[0]['value'] - 1) * 100, statistics.stdev(returns) * 100]
    return features if all(math.isfinite(v) for v in features) else None


def _estimate(training, features):
    scales = [statistics.pstdev(row['features'][i] for row in training) or 1 for i in range(2)]
    nearest = sorted(training, key=lambda row: math.hypot(*((row['features'][i] - features[i]) / scales[i] for i in range(2))))[:POLICY['maximumAnalogues']]
    values = [row['returnPercent'] for row in nearest]
    lower = statistics.mean(values) - 1.96 * statistics.stdev(values) / math.sqrt(len(values))
    support = all(min(row['features'][i] for row in training) <= features[i] <= max(row['features'][i] for row in training) for i in range(2))
    return {'withinObservedFeatureRange':support, 'medianPercent': statistics.median(values), 'meanPercent': statistics.mean(values),
            'p10Percent': _percentile(values, .1), 'p90Percent': _percentile(values, .9),
            'meanLowerHeuristicPercent': lower, 'positiveOutcomes': sum(v > 0 for v in values),
            'samples': len(values), 'sampleIds': [row['id'] for row in nearest]}


def evaluate_prices(observations, at, round_trip_bps=None):
    """No random splits, synthetic sessions, optimized thresholds or LLM numbers."""
    prepared, exclusions = _prepare(observations, at)
    history, error = _prices(prepared, at)
    result = {'modelVersion': MODEL_VERSION, 'policy': POLICY, 'asOf': at, 'status': 'Insufficient data',
              'blockers': [], 'exclusions': exclusions, 'forecast': None, 'entrySignal': False,
              'validation': None, 'historySessions': len(history), 'roundTripCostBps': round_trip_bps,
              'formula': 'gross_return_percent = (exit_price / entry_price - 1) * 100; conditional_net_return_percent = gross_return_percent - supplied_round_trip_bps / 100',
              'method': 'Fixed 20-session momentum/volatility nearest historical analogues; 5-session holding horizon; next-source-session entry.',
              'limitations': ['Empirical return ranges are model estimates, not guaranteed returns or calibrated prediction intervals.',
                  'Hypothetical outcomes use provider daily prices; executable fills, taxes and liquidity are not established.',
                  'The mean-minus-1.96-standard-errors gate is an approximate research rule; non-overlap does not prove statistical independence.',
                  'Validation tests a price signal within the currently researched universe; it does not backtest historical topic selection or establish causal effects.',
                  'Macroeconomic, financial and textual records affect evidence validity and are retained as context; their return effects are not invented.']}
    quotes = [r for r in prepared if r.get('metric') in PRICE_METRICS-{'total_return_index'} and r['value']>0 and r.get('unit') and _currency(r)]
    quote = max(quotes,key=lambda r:r['observedAt'],default=None)
    result['latestQuote'] = {**_record(quote),'currency':_currency(quote)} if quote else None
    if error: result['blockers'].append(error)
    if len(history) > POLICY['maximumHistorySessions']:
        result['excludedOlderSessions'] = len(history) - POLICY['maximumHistorySessions']
        history = history[-POLICY['maximumHistorySessions']:]
    result['usedHistorySessions'] = len(history)
    if not history: return result
    result['latestPrice'] = {**_record(history[-1]),'currency':_currency(history[-1])}
    if quote and quote['observedAt'] > history[-1]['observedAt'] and _currency(quote)==_currency(history[-1]) and quote.get('adjustment')==history[-1].get('adjustment') and abs(quote['value']/history[-1]['value']-1)*100 > POLICY['providerDisagreementPercent']:
        result['blockers'].append('The newer market quote has moved beyond the daily model review threshold; await refreshed session features.')
    result['historyInputs'] = [_record(r) for r in history]
    result['selectedPriceSourceId'] = history[-1]['sourceId']
    competing = [r for r in prepared if r.get('metric') in PRICE_METRICS and r.get('frequency')=='daily' and r['value']>0 and r['sourceId'] != history[-1]['sourceId'] and r.get('currency')==history[-1].get('currency') and r.get('adjustment')==history[-1].get('adjustment') and abs(r['observedAt']-history[-1]['observedAt']) <= 2*a.HOUR]
    result['competingCurrentInputIds'] = [r['id'] for r in competing]
    if any(abs(r['value']/history[-1]['value']-1)*100 > POLICY['providerDisagreementPercent'] for r in competing):
        result['blockers'].append('Comparable current providers disagree beyond the declared 1% review threshold.')
    result['historyInputIds'] = [r['id'] for r in history]
    if at - history[-1]['observedAt'] > POLICY['marketMaxAgeHours'] * a.HOUR:
        result['blockers'].append('The comparable daily market observation is stale.')
    if round_trip_bps is None:
        result['blockers'].append('Enter estimated round-trip fees and slippage; no zero-cost assumption is supplied.')
        cost = 0  # Gross exploratory statistics only; eligibility remains blocked.
    else:
        if isinstance(round_trip_bps, bool) or not math.isfinite(float(round_trip_bps)) or not 0 <= float(round_trip_bps) <= 1000:
            raise ValueError('Round-trip cost must be a finite number from 0 to 1000 basis points')
        cost = float(round_trip_bps) / 100
    result['returnBasis'] = 'Gross exploratory' if round_trip_bps is None else 'Net of user-specified round-trip cost assumption'
    n, lookback, horizon = len(history), POLICY['lookbackSessions'], POLICY['horizonSessions']
    samples = []
    # Striding horizon+1 prevents adjacent decision/entry/exit windows overlapping.
    for i in range(lookback, n - horizon - 1, horizon + 1):
        window = history[i-lookback:i+1]
        if not all(_daily_gap(left, right) for left, right in zip(window, window[1:])): continue
        decision = max(row['_available'] for row in window)
        decision = max(decision, history[i]['observedAt'])
        entry, final = history[i+1], history[i+1+horizon]
        if decision >= entry['observedAt']: continue  # Historical backfill cannot masquerade as an issued signal.
        if not all(_daily_gap(left, right) for left, right in zip(history[i:i+horizon+1], history[i+1:i+horizon+2])): continue
        value = (final['value'] / entry['value'] - 1) * 100 - cost
        if not math.isfinite(value): continue
        features = _features(window)
        if features is None: continue
        samples.append({'id': history[i]['id'], 'features': features, 'decisionAt': decision,
                        'entryAt': entry['observedAt'], 'exitAt': final['observedAt'],
                        'outcomeAvailableAt': max(entry['_available'], final['_available'], final['observedAt']),
                        'returnPercent': value, 'inputIds': [r['id'] for r in window] + [entry['id'], final['id']]})
    result['pointInTimeSamples'] = len(samples)
    result['excludedAvailabilityOrGaps'] = max(0, len(range(lookback, n-horizon-1, horizon+1)) - len(samples))
    validation = []
    for sample in samples:
        training = [r for r in samples if r['exitAt'] < sample['decisionAt'] and r['outcomeAvailableAt'] < sample['decisionAt']]
        if len(training) < POLICY['minimumTrainingSamples']: continue
        forecast = _estimate(training, sample['features'])
        baseline = statistics.median(r['returnPercent'] for r in training)
        validation.append({'decisionAt': sample['decisionAt'], 'entryAt': sample['entryAt'], 'exitAt': sample['exitAt'],
                           'predictedMedianPercent': forecast['medianPercent'], 'baselineMedianPercent': baseline,
                           'actualPercent': sample['returnPercent'], 'signal': sample['features'][0] > 0 and forecast['meanLowerHeuristicPercent'] > 0 and forecast['withinObservedFeatureRange'],
                           'lastTrainingOutcomeAvailableAt': max(r['outcomeAvailableAt'] for r in training)})
    if validation:
        mae = statistics.mean(abs(r['predictedMedianPercent'] - r['actualPercent']) for r in validation)
        baseline_mae = statistics.mean(abs(r['baselineMedianPercent'] - r['actualPercent']) for r in validation)
        signals = [r['actualPercent'] for r in validation if r['signal']]
        lower = statistics.mean(signals) - 1.96 * statistics.stdev(signals) / math.sqrt(len(signals)) if len(signals) > 1 else None
        result['validation'] = {'samples': len(validation), 'signalSamples': len(signals), 'medianAbsoluteErrorPercent': statistics.median(abs(r['predictedMedianPercent']-r['actualPercent']) for r in validation),
                                'meanAbsoluteErrorPercent': mae, 'baselineMeanAbsoluteErrorPercent': baseline_mae,
                                'meanSignalReturnPercent': statistics.mean(signals) if signals else None,
                                'meanSignalLowerHeuristicPercent': lower, 'signalLosses': sum(v < 0 for v in signals),
                                'worstSignalReturnPercent': min(signals) if signals else None, 'folds': validation}
        if len(validation) < POLICY['minimumValidationSamples']: result['blockers'].append('Too few chronological validation outcomes.')
        if len(signals) < POLICY['minimumValidationSignals']: result['blockers'].append('Too few held-out entry-signal outcomes.')
        if mae >= baseline_mae: result['blockers'].append('The analogue model has not beaten its same-fold unconditional median baseline.')
        if lower is None or lower <= 0: result['blockers'].append('Held-out signal results do not clear the positive-return gate after specified costs.')
    else:
        result['blockers'].append('No purged chronological validation outcomes are available; backfilled history alone cannot validate timing.')
    current_window = history[-lookback-1:]
    if len(current_window) != lookback+1 or not all(_daily_gap(left,right) for left,right in zip(current_window,current_window[1:])):
        result['blockers'].append('A complete, comparable 20-session feature window is missing.')
    elif len(samples) < POLICY['minimumTrainingSamples']:
        result['blockers'].append('Too few historical outcomes with demonstrable point-in-time availability.')
    elif _features(current_window) is None:
        result['blockers'].append('The source prices yield numerically unstable feature values.')
    else:
        features = _features(current_window)
        training = [r for r in samples if r['outcomeAvailableAt'] <= at]
        result['features'] = {'momentumPercent': features[0], 'dailyLogReturnVolatilityPercent': features[1]}
        forecast = _estimate(training, features)
        result['forecast'] = forecast
        result['entrySignal'] = features[0] > 0 and forecast['meanLowerHeuristicPercent'] > 0 and forecast['withinObservedFeatureRange']
        if not result['entrySignal']: result['blockers'].append('The current measured features do not satisfy the entry rule.')
    result['status'] = 'Eligible entry signal' if not result['blockers'] else 'Wait / insufficient evidence'
    result['outcomeSamples'] = samples
    return result


class RecommendationEngine:
    def __init__(self, service):
        self.s, self.db = service, service.db
        self.cache = OrderedDict()
        self.lock = threading.RLock()

    def queue_due(self, at=None):
        at = at or now_ms()
        queued = []
        for snapshot in sorted(self.db.scan('recommendationSnapshot'), key=lambda row:row.get('asOf',0)):
            board = self.db.get('researchBoard', snapshot['boardId'])
            if not board or board.get('archived'): continue
            if at - snapshot.get('asOf',0) < 60000: continue
            cached = self.cache.get((board['ownerId'], board['id']))
            signature = (tuple(self.db.kind_revisions.get(k,0) for k in DEPENDENCIES), tuple(board.get('branchTopics',[])),board.get('expansionState'),board.get('archived'))
            if cached and cached[0] == signature and at < cached[1]: continue
            # At most four reviews are queued per scheduler pass; normal worker leases apply.
            active = any(job['payload'].get('boardId')==board['id'] for job in self.db.jobs('queued',1000)+self.db.jobs('running',1000) if job['kind']=='recommendation-review')
            if active: continue
            queued.append(self.db.enqueue('recommendation-review', {'ownerId':board['ownerId'],'boardId':board['id']}, 'recommendation-review:'+board['id']+':'+str(at//60000)))
            if len(queued)>=4: break
        return queued

    def settings(self):
        return {'roundTripCostBps': None, **(self.db.get('setting', 'recommendations') or {})}

    def configure(self, values):
        value = values.get('roundTripCostBps')
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not 0 <= value <= 1000):
            raise ValueError('Round-trip fees and slippage must be 0–1000 basis points or null')
        record = {'roundTripCostBps': value, 'updatedAt': now_ms()}
        self.db.put('setting', 'recommendations', record)
        return self.settings()

    def _context(self, detail):
        """All stored documents are checked, including branch directions and adverse sources."""
        topic_ids = [detail['board']['topicId'], *detail['board'].get('branchTopics', [])]
        topics = [self.db.get('topicPortfolio', tid) for tid in topic_ids]
        topics = [t for t in topics if t and not t.get('deleted')]
        graph = detail['graph']
        explicit = {r['documentId'] for n in graph['nodes'] + graph['edges'] for r in n.get('evidence', [])}
        explicit.update(d['id'] for t in topics for d in t.get('evidence', []))
        assets = {row['id']: row for row in self.db.scan('asset') if row.get('assetClass') in {'equity', 'crypto'} and row.get('identityVerified')}
        sources = {r['id']:r for r in self.db.scan('source')}
        docs, considered, relevance = {}, 0, defaultdict(list)
        for doc in self.db.scan('document'):
            considered += 1
            matching = [t for t in topics if self.s.topics._match(doc, {**t, '_subjectNames': self.s.topics._subject_names(t)})['matches']]
            if doc['id'] not in explicit and not matching: continue
            docs[doc['id']] = doc
            for asset_id, asset in assets.items():
                company_id = str(doc.get('companyId', '')).lstrip('0')
                owned = bool(asset.get('cik') and company_id == str(asset['cik']).lstrip('0')) or company_id == asset_id
                for passage in doc.get('text','').splitlines() or [doc.get('text','')]:
                    # A source-backed match is relevance, not a claim of revenue exposure or causation.
                    if not owned and not self.s.topics._asset_mentioned(passage, asset, doc['id'] in asset.get('triggerDocumentIds', [])): continue
                    if not matching and doc['id'] not in explicit: continue
                    relevance[asset_id].append({'documentId': doc['id'], 'version': doc['version'], 'quote': passage[:1800],
                                                'sourceId': doc['sourceId'], 'url': doc.get('url'), 'basis': 'Source-supported research relevance; financial exposure is not implied'})
                    break
        # Include instrument IDs already discovered on every research branch.
        for n in graph['nodes']:
            asset_id = n.get('assetId')
            if asset_id in assets:
                relevance[asset_id].extend({**r, 'basis':'Cited observation-board instrument'} for r in n.get('evidence',[]))
        for t in topics:
            for row in t.get('entries', []) + t.get('candidates', []):
                if row.get('assetId') in assets:
                    relevance[row['assetId']].extend(row.get('topicMatch', []))
        claims = [r for r in self.db.scan('claim') if r.get('documentId') in docs]
        return topics, assets, sources, docs, claims, relevance, considered

    def board(self, owner, board_id):
        # Authorization is checked on every cache hit as well as every computation.
        detail = self.s.network_research.board(owner, board_id)
        at = now_ms()
        signature = (tuple(self.db.kind_revisions.get(k, 0) for k in DEPENDENCIES),
                     tuple(detail['board'].get('branchTopics', [])), detail['board'].get('expansionState'), detail['board'].get('archived'))
        key = owner, board_id
        with self.lock:
            cached = self.cache.get(key)
            if cached and cached[0] == signature and at < cached[1]:
                self.cache.move_to_end(key)
                return cached[2]
            result = self._build(detail, at)
            # If collection changed while computing, do not publish an obsolete entry signal.
            after = tuple(self.db.kind_revisions.get(k, 0) for k in DEPENDENCIES)
            if after != signature[0]:
                for item in result['assets']:
                    item['status'] = 'Review required'
                    item['potentialReturn'] = None
                    item['timing'] = 'Wait for the revised inputs to be assessed.'
                    item['blockers'].append('Inputs changed during calculation; recomputing on the next update.')
                result['status'] = 'Review required'
                result['eligibleCount'] = 0
            result['inputSignature'] = a.digest(dumps(signature))
            previous = self.db.get('recommendationSnapshot', board_id)
            material = a.digest(dumps({'assets':[{k:v for k,v in r.items() if k not in {'analysis'}} for r in result['assets']], 'sourceManifest':result['sourceManifest'], 'settings':result['settings'], 'modelVersion':MODEL_VERSION}))
            if not previous or previous.get('materialFingerprint') != material:
                result['revision'] = (previous or {}).get('revision',0)+1
                result['whatChanged'] = self._changes(previous, result)
                saved = {**result, 'ownerId': owner, 'materialFingerprint': material}
                self.db.put('recommendationSnapshot', board_id, saved)
                self.db.put('recommendationRevision', board_id+':'+str(result['revision']), saved)
            else:
                result['revision'], result['whatChanged'] = previous['revision'], previous['whatChanged']
                self.db.put('recommendationSnapshot', board_id, {**previous, 'asOf':at})
            # Dataset updates invalidate immediately; the clock also expires stale prices.
            expiry = min([at+300000]+[r['expiresAt'] for r in result['assets'] if r.get('expiresAt') and r['expiresAt']>at])
            self.cache[key] = signature, expiry, result
            if len(self.cache)>32: self.cache.popitem(last=False)
            return result

    @staticmethod
    def _changes(previous, result):
        if not previous: return ['Initial evidence-bound recommendation assessment.']
        old = {r['assetId']:r for r in previous.get('assets',[])}
        new = {r['assetId']:r for r in result['assets']}
        changes = []
        for asset_id in old.keys() | new.keys():
            if asset_id not in new: changes.append(asset_id+': topic connection removed; recommendation withdrawn.')
            elif asset_id not in old: changes.append(asset_id+': newly supported topic candidate.')
            elif old[asset_id]['status'] != new[asset_id]['status']: changes.append(asset_id+': '+old[asset_id]['status']+' → '+new[asset_id]['status'])
            elif old[asset_id].get('dataFingerprint') != new[asset_id].get('dataFingerprint'): changes.append(asset_id+': source evidence or market observations revised; forecast recalculated.')
        return changes or ['Evidence, validation, costs or freshness changed; assessment recalculated.']

    def _build(self, detail, at):
        topics, assets, sources, docs, claims, relevance, considered = self._context(detail)
        candidate_ids = set(relevance)
        price_rows, counts, context_rows = defaultdict(list), defaultdict(int), defaultdict(dict)
        for kind in ('observation','observationVintage'):
            for row in self.db.scan(kind):
                if row.get('assetId') in candidate_ids:
                    counts[row['assetId']] += 1
                    if row.get('metric') in PRICE_METRICS: price_rows[row['assetId']].append(row)
                    elif (_availability(row) or at+1) <= at and (sources.get(row.get('sourceId')) or {}).get('enabled'):
                        context_key=tuple(row.get(k) for k in ('metric','sourceId','unit','currency','accountingBasis'))
                        previous=context_rows[row['assetId']].get(context_key)
                        rank=(str(row.get('periodEnd','')),row.get('observedAt',0),_availability(row))
                        prior_rank=(str(previous.get('periodEnd','')),previous.get('observedAt',0),_availability(previous)) if previous else None
                        if previous is None or rank>prior_rank: context_rows[row['assetId']][context_key]=row
        result = {'boardId': detail['board']['id'], 'topicId': detail['board']['topicId'], 'asOf': at,
                  'modelVersion': MODEL_VERSION, 'status': 'Assessed', 'assets': [], 'settings': self.settings(),
                  'coverage': {'storedDocumentsScreened': considered, 'relevantDocuments':len(docs), 'branchesIncluded':len(topics),
                               'candidateAssets':len(candidate_ids), 'scope':'All stored documents screened for the topic and its saved branches. Uncollected, inaccessible and undiscovered sources are outside this coverage.'},
                  'sourceManifest':[{'id':d['id'],'version':d['version'],'sourceId':d['sourceId'],'url':d.get('url'),'title':d.get('title')} for d in docs.values()],
                  'method': 'Cited topic relevance selects provider-identified assets. Source contradictions veto entries. Historical price analogues estimate conditional returns only after chronological validation.',
                  'limitations':['The algorithm cannot know all existing information. Coverage is the collected records listed here.', 'Text co-mentions and correlations do not establish a financial exposure or cause a return.']}
        for asset_id in sorted(candidate_ids):
            asset = assets[asset_id]
            refs = {dumps(r):r for r in relevance[asset_id]}.values()
            valid_refs, evidence_gaps = [], []
            for ref in refs:
                doc = self.db.get('document', ref.get('documentId',''))
                source = sources.get((doc or {}).get('sourceId')) or {}
                quote = ref.get('quote','')
                if not doc or doc['version'] != ref.get('version') or not quote or quote not in doc.get('text',''):
                    evidence_gaps.append('A cited topic connection is missing, revised or has no exact supporting quote.')
                elif not source.get('enabled'):
                    evidence_gaps.append('A supporting topic source has been disabled.')
                else:
                    issuer = bool(asset.get('cik') and str(doc.get('companyId','')).lstrip('0') == str(asset['cik']).lstrip('0'))
                    named = self.s.topics._asset_mentioned(quote, {**asset,'ticker':''}, doc['id'] in asset.get('triggerDocumentIds',[]))
                    if not (issuer or named): evidence_gaps.append('The quoted source does not unambiguously identify this exact instrument; ticker-only matches are insufficient.')
                    else: valid_refs.append({**ref, 'sourceId':source['id'], 'url':doc.get('url')})
            if not any(sources[r['sourceId']].get('tier')=='primary' for r in valid_refs):
                evidence_gaps.append('Primary-source support for this asset/topic connection is missing.')
            if any(t.get('pendingEvidenceChanges') or t.get('marketResearchStale') for t in topics):
                evidence_gaps.append('Topic evidence changed; research reassessment is pending.')
            # Conservative: an unresolved conflict anywhere in relevant topic records blocks an entry.
            adverse = [c['id'] for c in claims if c.get('status') in BAD_STATES or c.get('reviewRequired') and c.get('history')]
            if adverse or any(r.get('status') in BAD_STATES or r.get('reviewRequired') for r in detail['graph']['nodes']+detail['graph']['edges']):
                evidence_gaps.append('Relevant contradictory, retracted or revised evidence requires review.')
            if not topics or not topics[0].get('enabled',True) or detail['board'].get('expansionState')!='running' or detail['board'].get('archived'):
                evidence_gaps.append('Research is stopped or paused; no active entry recommendation is issued.')
            enabled_prices = [r for r in price_rows[asset_id] if (sources.get(r.get('sourceId')) or {}).get('enabled') and (sources.get(r.get('sourceId')) or {}).get('tier')=='primary']
            model = evaluate_prices(enabled_prices, at, self.settings()['roundTripCostBps'])
            blockers = list(dict.fromkeys(evidence_gaps + model['blockers']))
            price = model.get('latestQuote') or model.get('latestPrice')
            daily_price = model.get('latestPrice')
            forecast = model.get('forecast')
            context = [_record(r) for r in context_rows[asset_id].values()]
            row = {'assetId':asset_id,'ticker':asset.get('ticker'),'name':asset.get('name'),'assetClass':asset.get('assetClass'),
                   'status':'Eligible entry signal' if not blockers else 'Wait / insufficient evidence', 'blockers':blockers,
                   'topicEvidence':valid_refs,'conflictIds':adverse,'market':price,'analysis':model,
                   'expiresAt':min(r['observedAt'] for r in [price,daily_price] if r)+POLICY['marketMaxAgeHours']*a.HOUR if price else None,
                   'holdingHorizonSessions':POLICY['horizonSessions'],
                   'timing':'Consider the next provider session only while this signal remains eligible; refresh before acting.' if not blockers else 'Wait for the listed evidence and validation gates to clear.',
                   'potentialReturn':forecast if not blockers else None,
                   'dataFingerprint':a.digest(dumps({'asset':asset,'evidence':list(valid_refs),'claims':claims,'prices':enabled_prices,'contextObservations':context})),
                   'observationsScreened':counts[asset_id], 'contextObservations':context,
                   'unmodeledContext':'Financial statements, contracts, costs and macro records are evidence context. No unvalidated numerical return effect is assigned to them.'}
            result['assets'].append(row)
        result['assets'].sort(key=lambda r:(r['status']!='Eligible entry signal', -(r.get('potentialReturn') or {}).get('medianPercent',0),r['assetId']))
        result['eligibleCount'] = sum(r['status']=='Eligible entry signal' for r in result['assets'])
        return result
