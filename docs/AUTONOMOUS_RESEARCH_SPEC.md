# Autonomous Market Research & Investment Intelligence Engine

## Core objective

The application should function as an autonomous financial research analyst that continuously investigates global events, economic conditions, stock markets, cryptocurrency, political developments, and corporate performance to identify investments and market sectors worth monitoring.

The system's primary responsibility is to discover, research, verify, compare, and maintain investment research profiles and watch portfolios using real, traceable information.

It should not simply summarize news or identify stocks experiencing price increases. It should investigate what actually changed, whether those changes are supported by financial evidence, which companies or assets are directly affected, and whether the available evidence warrants further attention.

Most importantly:

The application must never fabricate facts, financial figures, source references, causal relationships, predictions, or recommendations.

Every factual statement must be supported by retrieved evidence, verified numerical data, or a transparent calculation performed on that data.

A research conclusion can involve interpretation, but the distinction between an observed fact and an analytical interpretation must always be explicit. The system cannot guarantee that every source is correct, but it can refuse to present unverified claims as established facts.

## 1. Exactly what the application should do

The application should autonomously perform the following research cycle, without requiring the user to initiate individual investigations.

01

Observe

Continuously ingest current financial, economic, political, corporate, and global news data.

02

Detect

Identify measurable market changes, emerging developments, and events that warrant investigation.

03

Investigate

Research the event using original records, independent reporting, financial statements, and market data.

04

Correlate

Compare the event with historical market behavior and identify documented relationships without assuming causation.

05

Evaluate

Assess financial performance, valuation, exposure, risks, and competing explanations.

06

Profile

Build or update an evidence-backed research profile for each relevant asset or company.

07

Curate

Add qualifying assets to thematic watch portfolios with a documented reason for inclusion.

08

Monitor

Recheck the supporting evidence and update, downgrade, or remove assets as conditions change.

This cycle should run continuously and trigger additional investigations when new developments materially affect existing profiles.

The research system should maintain three principal outputs: individual asset profiles, curated market watch portfolios, and autonomous research reports.

## 2. Autonomous investigation categories

The AI should be capable of starting investigations from any of these information categories.

| Research area          | What the AI must evaluate                                                                      |
| ---------------------- | ---------------------------------------------------------------------------------------------- |
| Stock performance      | Price and volume history, volatility, relative performance, trading activity                   |
| Corporate fundamentals | Revenue, profitability, margins, debt, cash flow, financial guidance, filings                  |
| Company growth         | Historical revenue growth, earnings growth, customer or production growth when verifiable      |
| Economic conditions    | Inflation, employment, rates, GDP, credit conditions, consumer activity                        |
| Political developments | Passed legislation, proposed rules, tariffs, sanctions, government contracts, fiscal policies  |
| World events           | Supply disruptions, conflicts, trade agreements, policy changes, natural disasters             |
| Cryptocurrency         | Price, liquidity, trading volume, circulating supply, tokenomics, verifiable on-chain activity |
| Industry developments  | Competitive activity, supply chains, regulation, capital spending, industry demand             |
| Public sentiment       | Observable reporting and discussion patterns, clearly separated from verified factual evidence |

The AI should be able to recognize an important development in one domain, identify potentially related assets, and initiate deeper research without a user supplying the ticker symbols.

For example, a confirmed change in trade policy could initiate research into publicly traded companies that disclose relevant geographic revenue, production exposure, or supply-chain dependencies.

The application must not conclude that those stocks will increase or decrease in value merely because the trade policy changed.

That requires additional evidence, and future market direction remains uncertain.

## 3. Build complete, continuously updated asset research profiles

Each investment candidate should have a persistent research profile, automatically created and maintained by the AI.

The profile should contain considerably more than an AI-written company description.

### Required profile structure

| Section             | Required content                                                                               |
| ------------------- | ---------------------------------------------------------------------------------------------- |
| Identity            | Verified company/asset name, ticker, exchange or blockchain, instrument identifiers            |
| Market performance  | Latest verified price, timestamp, price history, trading volume, volatility                    |
| Financial health    | Revenue, earnings, margins, debt, cash flow, assets, liabilities                               |
| Growth              | Historical growth rates and changes in actual reported results                                 |
| Valuation           | Applicable valuation metrics calculated from sourced financial and price data                  |
| Market position     | Verifiable products, competitors, market exposure, and geographic operations                   |
| Economic exposure   | Documented relationships to inflation, interest rates, currencies, and other economic factors  |
| Political exposure  | Applicable laws, regulations, contracts, government actions, and proposed policy changes       |
| Recent developments | Verified announcements, filings, reports, and material events                                  |
| Positive indicators | Evidence supporting favorable business or financial developments                               |
| Negative indicators | Evidence of financial weaknesses, operational concerns, or material risks                      |
| Research conclusion | Evidence-based explanation of why the asset warrants monitoring                                |
| Monitoring criteria | Specific measurable changes that would strengthen or weaken the research case                  |
| Source history      | Original records, publication dates, financial data timestamps, and previous profile revisions |

All numerical metrics should be calculated by application code using retrieved values. OpenAI should explain the results, not independently generate prices, financial figures, percentages, or ratios.

For example, revenue growth must use financial results from the relevant periods. If the necessary financial statement is unavailable, the application should display "Data unavailable" rather than estimating a figure.

The SEC's EDGAR APIs provide structured company filings and XBRL financial data suitable for supporting U.S. public-company research.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://www.sec.gov\&sz=32)

EDGAR Application Programming Interfaces (APIs)



### How each profile should behave

Profiles should be living research records.

If an earnings report is released, the system should collect it, update the relevant financial information, recalculate affected metrics, identify differences from previous results, and reconsider the profile's research status.

If an earlier claim is disproven, all conclusions relying on that claim must be re-evaluated.

If the data becomes stale, the profile should display its last verified state rather than presenting it as current.

The user should have access to a chronological history showing what changed and why.

## 4. Portfolio generation: Collections of assets worth watching

I would separate research portfolios from actual investment portfolios.

Your application's primary output should be a selection of companies, ETFs, securities, or crypto assets that qualify for additional attention based on documented financial or market developments.

It should not imply that an asset should be purchased or that a particular return is expected.

### Autonomous portfolio categories

Documented Growth

Assets exhibiting measurable growth in reported business or financial metrics, with financial health and valuation evaluated separately.

Political and Regulatory Exposure

Assets with demonstrable exposure to enacted legislation, proposed policies, government spending, tariffs, sanctions, or regulatory actions.

Global Economic Exposure

Companies and industries with documented connections to economic indicators, trade activity, commodity prices, or currency fluctuations.

Unusual Market Activity

Assets showing statistically unusual price, volume, volatility, or liquidity changes, regardless of whether an explanation has been identified.

Digital Asset Intelligence

Cryptocurrency projects with verified changes in liquidity, transaction activity, token supply, governance, or other observable fundamentals.

Research Opportunities

Assets with significant confirmed developments whose market implications remain uncertain and require continued investigation.

### Rules for including an asset

Before an asset can enter a curated portfolio, the system should establish:

1. The asset's identity and the existence of reliable market data.
2. At least one independently verifiable reason to investigate it.
3. The specific evidence supporting its inclusion.
4. The relevant observation period.
5. Material risks, contradictory evidence, and missing information.
6. A measurable condition for continued monitoring or removal.

A single verified event can justify investigation. It does not automatically justify a favorable investment conclusion.

Portfolio entries should be classified as:

- Under investigation: An observed development triggered research, but supporting evidence remains incomplete.
- Qualified for monitoring: The asset meets the portfolio's documented research criteria.
- Continued monitoring: The original criteria remain satisfied, with no material invalidating developments.
- Review required: New evidence has materially altered the research case.
- Removed: The asset no longer satisfies the portfolio's inclusion criteria.

Each portfolio should also summarize sector concentration, geographic exposure, shared risk factors, and correlations calculated over stated historical windows.

An asset appearing in several portfolios must not be counted as several independent investment opportunities.

The system should not invent portfolio weights, expected returns, or price targets. If you later add portfolio optimization, it should operate on explicit user-provided objectives and risk constraints, with assumptions disclosed separately.

## 5. Economic and political intelligence must be tied to observable outcomes

This should be a major part of the application's autonomous reasoning.

Political events and economic changes can have broad consequences, but the system needs to distinguish policy announcements from actual implementation and observed market effects.

### Economic research

The application should monitor:

- Inflation measures such as CPI, PCE, and PPI.
- Central-bank policy rates and published decisions.
- Employment data and wage growth.
- GDP and industrial production.
- Consumer spending and confidence indicators.
- Government bond yields and credit conditions.
- Commodity prices and foreign exchange rates.
- Business investment and publicly reported corporate spending.

The AI should investigate how companies are exposed to those indicators using their actual financial statements, disclosures, and measurable historical relationships.

A statistical correlation may be calculated and reported, but it must be labeled as such rather than treated as proof of cause and effect.

Important: Economic information is frequently revised. The application's historical research must preserve what data was available at the time.

FRED and ALFRED support observation history and real-time data vintages, making this possible for supported series.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://fred.stlouisfed.org\&sz=32)

FRED

+1



### Political research

Political research should distinguish:

| Political information | Required handling                                                   |
| --------------------- | ------------------------------------------------------------------- |
| Campaign promise      | Attributed statement, not implemented policy                        |
| Proposed legislation  | Proposal with verified procedural status                            |
| Passed legislation    | Confirmed passage and any remaining legal steps                     |
| Enacted law           | Verified legal text and effective dates                             |
| Regulatory proposal   | Proposed requirements and consultation status                       |
| Final regulation      | Published final requirements and applicable dates                   |
| Government contract   | Verified award details, recipient, value, and terms where available |
| Political commentary  | Attributed opinion, not established fact                            |

Political party affiliation should never determine whether an investment receives a favorable or unfavorable assessment.

The system should evaluate the substance of the policy, the documented exposure of affected companies, and any actually observed financial or market consequences.

### Event-to-market analysis

The AI should construct event timelines that combine political or economic developments with financial observations.

An event study may quantify price behavior before and after an announcement, compare it with a benchmark, and report abnormal returns where the necessary data exists.

However, it must not say that the announcement caused the movement without additional evidence.

Use language such as "Shares declined following the announcement" when the chronology is established, rather than "The announcement caused the decline" when causality has not been established.

## 6. Autonomous re-research and monitoring

The AI should continue monitoring research subjects after they have been added to the platform.

It should not merely refresh a summary on a schedule.

### Event-driven research triggers

| Trigger                                    | Autonomous action                                                 |
| ------------------------------------------ | ----------------------------------------------------------------- |
| New company filing                         | Extract reported changes and re-evaluate financial profile        |
| New economic release                       | Update relevant macroeconomic indicators and affected research    |
| Significant price or volume anomaly        | Investigate whether verified developments explain the observation |
| Regulatory status change                   | Re-evaluate documented company or industry exposure               |
| Credible contradictory report              | Reopen affected claims and conclusions                            |
| Company guidance revision                  | Compare revised guidance with previous disclosures                |
| Earnings release                           | Update financial results and historical comparisons               |
| Important source correction                | Recalculate or retract dependent findings                         |
| Cryptocurrency liquidity or supply change  | Verify against relevant market and blockchain records             |
| Portfolio inclusion criteria no longer met | Review the asset's classification and remove it when warranted    |

Statistical thresholds should be configurable and evaluated on historical data rather than arbitrarily defined by the language model.

The system should retain previous research reports and produce a meaningful "What changed?" explanation after each re-evaluation.

If a search finds no additional information, it should report that no new verified evidence was found in the sources checked. It should not assume that no new information exists anywhere.

## 7. OpenAI integration: Autonomous research analyst

OpenAI should act as the application's research coordinator, investigator, and report writer, not as its financial data provider or sole authority.

The integration should use the [OpenAI Responses API](https://developers.openai.com/api/reference/responses/overview?utm_source=chatgpt.com), which supports tool calling and external data access. Its web-search capabilities can support additional source discovery and investigative research.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://developers.openai.com\&sz=32)

OpenAI API Reference

+1



### What OpenAI should be responsible for

| Responsibility             | OpenAI's role                                                               |
| -------------------------- | --------------------------------------------------------------------------- |
| Research planning          | Determine which questions need investigation                                |
| News interpretation        | Extract factual assertions, affected entities, dates, and relevant context  |
| Source comparison          | Identify agreements, contradictions, and missing evidence                   |
| Relationship investigation | Propose connections to investigate, without declaring unsupported causality |
| Follow-up research         | Request additional data when information is incomplete                      |
| Profile compilation        | Turn verified findings into structured, readable research                   |
| Portfolio curation         | Explain which assets meet independently enforced inclusion rules            |
| Report generation          | Describe verified changes, uncertainty, risks, and monitoring criteria      |
| Research correction        | Revise conclusions when the underlying evidence changes                     |

### Required application tools

Expose a controlled set of read-only functions to the OpenAI integration.

Suggested research tool interface

These are proposed application functions, not built-in OpenAI API endpoints.

Source retrieval

`search_news(query, date_range, region)`

`retrieve_source_document(source_id)`

`get_company_filings(company_id, filing_type)`

`get_policy_records(jurisdiction, topic)`

Financial data

`get_market_history(instrument_id, date_range)`

`get_financial_statements(company_id, periods)`

`get_economic_series(series_id, date_range, vintage)`

`get_crypto_metrics(asset_id, network, date_range)`

Research and validation

`find_related_entities(event_id)`

`get_existing_research(instrument_id)`

`calculate_financial_metrics(dataset_ids)`

`validate_evidence_claim(claim_id, evidence_ids)`

`compare_research_versions(profile_id)`

OpenAI can request these functions, examine the returned evidence, and decide which additional research steps are necessary.

It should not be able to invent a function response or substitute an internally generated number when a tool fails.

### Recommended integration behavior

1. A research trigger originates from the existing ingestion or market analysis system.
2. The application creates a research task containing relevant evidence identifiers.
3. OpenAI receives the task and available research tools.
4. OpenAI investigates the subject, requesting further data as needed.
5. The application calculates all financial metrics independently.
6. OpenAI produces a structured research assessment.
7. A separate validation service checks the assessment against its cited evidence and source records.
8. Only validated content is published to the research profile or watch portfolio.

For research that requires many searches or substantial analysis, the Responses API supports longer-running requests using background mode.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://developers.openai.com\&sz=32)

OpenAI API



Use structured output schemas for research findings rather than relying on unstructured paragraphs. OpenAI's [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?utm_source=chatgpt.com) can enforce response structure, but your own application must still validate the factual content.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://developers.openai.com\&sz=32)

OpenAI API



## 8. Absolute evidence requirements

This is where I would enforce your requirement that nothing be assumed, guessed, or fabricated.

Every result should satisfy an explicit evidence contract.

### Evidence contract

| Requirement                  | Enforcement                                                                                    |
| ---------------------------- | ---------------------------------------------------------------------------------------------- |
| Factual claim                | Must reference a retrievable source record or underlying observation                           |
| Financial number             | Must originate from an authorized data feed or source document                                 |
| Calculated metric            | Must include underlying values, formula, units, and observation period                         |
| Historical comparison        | Must use comparable, appropriately adjusted data                                               |
| Political event              | Must include source, date, procedural status, and jurisdiction                                 |
| Causal conclusion            | Must be supported by evidence establishing more than chronological association                 |
| Company relationship         | Must be supported by ownership, filings, contractual disclosures, or other documented evidence |
| Forecast or projected return | Must not be presented as fact; omit when speculative analysis is disallowed                    |
| Research recommendation      | Must reference the validated findings justifying inclusion                                     |
| Missing information          | Must be explicitly marked as missing, stale, conflicting, or unverified                        |

### Data integrity requirements

Every numerical observation should preserve:

- Source identifier and retrieval timestamp.
- Observation timestamp and time zone.
- Original value, unit, and currency.
- Market session or financial reporting period.
- Adjustment methodology, where applicable.
- Original versus revised release status.
- Instrument identifier and data-provider identifier.

For stock market data, distinguish raw prices from split-adjusted or dividend-adjusted historical prices. For financial statements, identify the accounting period and reporting currency.

For economic indicators, preserve whether the number was initially released or subsequently revised.

For cryptocurrencies, distinguish tokens with similar symbols using chain and contract identifiers rather than relying solely on a ticker.

A recent AI analysis is not evidence that its underlying market data is recent. The application must assess freshness independently for every observation.

### Mandatory failure behavior

When sufficient evidence is unavailable, the system must:

1. Stop making the unsupported claim.
2. Identify the missing data.
3. Attempt additional authorized retrieval when appropriate.
4. Explain what can and cannot currently be verified.
5. Withhold or downgrade the affected recommendation.

It must never fill information gaps with estimates just to complete a report.

## 9. Required research output

The AI should generate two types of research reports: individual asset dossiers and cross-market intelligence reports.

### Individual asset dossier

Each dossier should use a consistent structure:

## Asset Research Profile

Required output template · No illustrative market figures

Instrument identity

Verified name, symbol, exchange, instrument type, identifiers

Current financial position

Latest supported measurements, reporting periods, historical comparisons

Verified developments

Events and disclosures with dates and direct evidence links

Positive and negative indicators

Both favorable and unfavorable findings, each independently substantiated

Broader market exposure

Documented economic, regulatory, geopolitical, and industry connections

Reason to monitor

Evidence-backed explanation of which research criteria the asset satisfies

Next verification triggers

Specific events, financial releases, or market conditions to recheck

Evidence status

Pending validation

Actual reports should include direct source citations, data timestamps, research status, and a complete revision history.

### Cross-market intelligence report

The second report type should examine a broader development and identify relevant investment candidates.

Its structure should answer:

What happened? A description limited to documented facts.

What financial changes have been observed? Verified figures, historical comparisons, and relevant market responses.

Which assets have documented exposure? Companies, funds, or digital assets linked through verifiable business or market relationships.

What remains uncertain? Missing evidence, disputed interpretations, and unsupported proposed explanations.

Which assets warrant additional monitoring? Candidates that satisfy defined research criteria.

What would change the assessment? Specific disclosures, economic releases, or observable developments.

These reports should be automatically regenerated when materially new evidence becomes available.

## 10. Final requirements for the application

The following is the functional specification I would give the development system.

Autonomous research system requirements

Use this checklist as an acceptance standard for the completed intelligence engine.

0 of 12 requirements reviewed

Reset

Research autonomy

Continuously discover and investigate relevant developments without requiring manual topic selection.

Financial grounding

Retrieve actual prices, financial statements, historical observations, and economic data before producing conclusions.

Cross-domain research

Investigate documented links among companies, markets, economic indicators, world news, and government actions.

OpenAI orchestration

Use OpenAI to determine research steps, investigate information, compare evidence, and formulate readable assessments.

Evidence validation

Reject unsupported statements before research findings are stored or published.

Asset profiles

Automatically create and update persistent, source-backed profiles for relevant market instruments.

Curated portfolios

Create and maintain watch portfolios using defined, measurable inclusion and removal rules.

Monitoring

Reopen research automatically when new verified financial, economic, political, or corporate information appears.

Transparent calculations

Calculate financial metrics with application code and preserve their inputs and methodology.

No invented data

Never fabricate values, sources, facts, event relationships, confidence levels, or expected investment returns.

Historical accountability

Preserve previous findings, source revisions, research changes, and the information available at each assessment date.

Failure handling

When evidence cannot be established, report the limitation and withhold unsupported conclusions.

&#x20;Copy requirements for Codex

The distinction I would enforce throughout the application is this:

OpenAI is allowed to identify questions, perform research, evaluate evidence, and explain conclusions. It is not allowed to create evidence.

With that restriction built into the data pipeline—not merely written into an AI prompt—the platform can become a continuously operating market research system that generates transparent, evidence-backed watch portfolios rather than speculative stock picks.