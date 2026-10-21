# Crawler — Deep Research Network

Start with a topic. Explore its evidence, companies, owners, products and markets on an editable observation board. Save private investigations and watch portfolios, then continue researching while the server runs.

## Start

From the `HTML Tests` folder:

```powershell
python CRAWLER/run.py --open-browser
```

Open **http://127.0.0.1:8765/CRAWLER/**. Python 3.11 or newer is required. The default server uses only the Python standard library; no package installation or frontend build is needed.

On Windows, double-click `CRAWLER/start.cmd` to start the server and open the correct address. Use the Python URL for topic research and OpenAI setup. A separate IDE/Live Server address such as port 5500 serves the HTML without the research API. Startup readiness is independent of archive synchronization; the search screen does not start legacy market-stream reconnects or dashboard polling.

Keep that process running for unattended collection, monitors, and scheduled briefs. Closing the browser does not stop the server. Stopping the process stops those services; queued work and source data survive a restart. For an always-on installation, run the command under your operating system's service manager. `--no-workers` serves saved research without starting collection. `--port`, `--host`, `--data-dir`, and `--no-default-sources` are supported.

The app still works under a plain static server or as a local page with browser-only storage. Server features appear automatically when the research API is available on the same origin. The old `CRAWLER.html` entry point is preserved.

## Runtime limits and stopping the server

The research server runs with **two** background workers by default and caps them at four. HTTP concurrency defaults to eight simultaneous requests (hard limit 32); requests beyond that limit receive a 503 response instead of launching unbounded handler threads. Browser data refreshes are staggered and the observation board slows its polling when research is idle.

On local hardware, adjust `CRAWLER_WORKERS`, `CRAWLER_HTTP_CONNECTIONS`, and `CRAWLER_SHUTDOWN_GRACE_SECONDS` in `.env`; use `--no-workers` to inspect saved research without collection. Performance depends on data volume and enabled feeds; these are limits, not measured guarantees.

**Stop the server:** Choose **Stop server** on the start page or **Stop research server** in the workspace (server owner only), or press Ctrl+C in the Python server terminal. SIGTERM is also handled. A shutdown request immediately stops new background scheduling, closes the HTTP listener, drains active research threads for a bounded grace period, and terminates managed media-validation subprocesses. Research records and queued work remain on disk. An in-flight job that cannot finish during the grace period may be retried after its durable lease expires on a later start; do not treat abrupt termination as guaranteed immediate task cancellation.

Connected browser tabs display a prominent **server offline** notice and stop live API refreshes once the server is unavailable. Browsers intentionally do not allow a server to forcibly close tabs that it did not open programmatically; external applications and operating-system processes are not killed. Closing the browser window alone does **not** stop an intentionally unattended research server.

**Security:** An earlier commit included a tracked `API KEY.txt` file containing a possible secret. The file has been removed from the current review branch and is now ignored, but it remains in existing Git history. Rotate any credentials that were stored in it and separately clean affected Git history if required. Never store API keys in the repository.

## Search first

The default page is a centered search bar beneath **“Where do I start”**. Enter a topic, industry, company, or idea. Results open an interactive **Research Observation Board**, followed by the source-linked market brief, drivers, risks, and connected **companies, markets, and financial institutions**. Click **Market brief** to jump directly to the report. **Your topics** reopens previous searches; a fresh visit starts with the clean search screen.

Topic research reads matching documents from the application's sources, using the connected OpenAI model to expand the research scope and synthesize a brief. Generated analysis carries exact supporting passages and source links; names on the watchlist must appear in cited records. Watch subjects do not need a stock quote or seven days of trading observations. Financial profiles retain their separate instrument identity, price and qualification checks and appear below the topic watchlist when available. An empty source set reports the actual coverage gap. Research lists have no allocation weights or expected returns.

Topics refresh every hour by default. Relevant source revisions and new asset observations bring the next review forward; pending provider collection schedules an earlier follow-up. Updates continue while the server runs, including when the browser is closed. Pause or resume a topic directly from its results. Job leases are renewed during long model investigations to avoid duplicate background execution.

Choose **Open workspace** to reach the detailed application. It retains three destinations:

- **Overview:** a persistent research question box, priority signals, market context, and latest reporting. Clicking a signal opens its sources and findings alongside the list. Clicking an asset opens its chart and mentions in that same contextual area. Sidebar shortcuts jump directly to market context or reporting. `Ctrl K` focuses search; `/` focuses research.
- **Watchlist:** saved investigations, notes, monitors, notifications, intelligence briefs, scenarios, and outcomes.
- **Sources & System:** source configuration, health, jobs and retry controls, document imports, quantitative measurements, historical replay, and audit integrity.

The default signal inspector puts findings, possible conflicts, and source links near the top. Advanced filters, raw records, detailed graphs, and manual review controls expand when needed. Only the first six signals are shown initially; search and filters immediately narrow the collection, and “Show more” expands the list. Mobile uses the same three destinations in a bottom navigation bar.

Existing asset tables, charts, penny-stock/token discovery, source-filtered mentions, social activity, and source diagnostics remain available in the overview and contextual inspector.

## Observation boards

Click a node to inspect evidence, original financial amounts and periods, bylines, source revisions, notes, and related entities. Click a line to see its exact supporting passage, relationship type, observation date, and review status.

- Drag nodes to arrange them; drag the canvas to pan; scroll or use zoom/fit controls. The minimap navigates the visible network.
- Double-click a node to expand collected relationships. **Research further** performs a new investigation into ownership, finances, contracts, suppliers, competitors, markets, contradictions, or a proposed connection.
- Drag a node's **+** handle to another node to propose a typed connection, or to empty canvas space to create a linked personal observation.
- Right-click to annotate, duplicate, hide, pin, collapse, or research. Shift-click selects multiple nodes for a named collection. Undo/redo applies to personal edits.
- **Save board** preserves positions, viewport, notes, personal nodes and connections, groups, pins and expansion state. **My Research** supports folders, renaming, duplication, archive/delete, JSON export and prior layout revisions.
- **Add to watch portfolio** preserves the subject, reason, originating board and relevant relationship IDs. Portfolios support descriptions, folders, editing, archive/delete, and updates when supporting evidence changes.

The board uses native DOM/SVG and progressive display (80 nodes initially, up to 700 collected nodes per view). Private overlays are separate from canonical source records. Source updates preserve layouts and annotations; stale citations require review. Extracted relationships are **Reported**, open branches are **Research questions**, and personal connections are **User assertions**. A server owner can explicitly record a relationship review in its evidence inspector. AI cannot assign Verified status. Citation validation checks document IDs, current versions, original quote spans, named endpoints, and relationship cues; it does not replace semantic review.

Article authors come from each feed/page's own credited metadata. Publisher-scoped author identities avoid silently merging namesakes. JSON-LD article authors and common author metadata are retained when present; missing bylines stay unavailable. Legal company identity remains unresolved unless authoritative identifiers are available. A name match alone does not link a company to a quoted security. Reported financial attributes preserve original source strings; calculated financial profiles use the existing deterministic engine and verified instrument identities. Registry subscriptions, financial feeds and procurement APIs are not bundled.

With **Keep research running automatically** enabled, source-backed company discoveries start bounded ownership investigations. Automatic expansion starts from at most two directly connected companies, follows at most two documented entities per step, and respects depth 1–3 and eight active tasks per board. Manual research works with background AI disabled. **Research queue** supports pause, resume and cancel, including on mobile. An already-running provider request may finish after cancellation; subsequent branch expansion stops. Tasks and source updates persist without an open browser.

The [expanded specification](docs/DEEP_RESEARCH_NETWORK_SPEC.md) is retained as a reference. Its illustrative companies and relationships are not seeded into the application. A particular article can only appear once an accessible, permitted original source has been collected.

## Personal accounts — Supabase

The supplied project is prefilled as **`https://lowvafwxnuqtogsfkmkd.supabase.co`**. To finish connecting it:

1. Start the Python server and open **Account → Account provider setup**. Enter the project's **publishable / anon key**, then choose **Verify & connect**. Alternatively set `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` in `CRAWLER/.env` and restart.
2. In Supabase Authentication, enable email/password sign-in and email confirmation. Configure email delivery and allow the local redirect URL **`http://127.0.0.1:8765/CRAWLER/account.html?view=callback`**. If using another host or port, allow its exact callback instead. For deployment set `CRAWLER_PUBLIC_URL` to the app's HTTPS origin and allow the corresponding callback.
3. Enable self-service account deletion by running [supabase-account-deletion.sql](docs/supabase-account-deletion.sql) in that project's SQL editor. It grants authenticated users a function that deletes only their own account. Alternatively configure a server-only `SUPABASE_SERVICE_ROLE_KEY`. This key must not be entered in the publishable-key form.
4. Use **Create account**, verify the email, and sign in. Account settings provide display-name editing, password changes/recovery, TOTP MFA, active-session revocation, personal-data export, and account deletion.

Authentication follows the official [Supabase password](https://supabase.com/docs/guides/auth/passwords) and [TOTP MFA](https://supabase.com/docs/guides/auth/auth-mfa/totp) interfaces. The app authenticates user tokens with Supabase, then issues an opaque HttpOnly, SameSite cookie. Provider access/refresh tokens remain in protected server storage; passwords are forwarded for authentication and never persisted. Account mutations require CSRF tokens; authentication and research requests have bounded rate limits.

Private boards and portfolios live in the research server's SQLite/PostgreSQL database, with ownership checked on every private API operation. Supabase manages account identity; this implementation does not expose research tables directly through Supabase's browser database API. Multiple devices must connect to the same running research server to share saved work. Source evidence is shared; notes, layouts, manual assertions, task ownership and portfolio selections are private. Ordinary accounts cannot configure provider credentials, change collectors, review canonical evidence, or access server-wide exports.

Local research remains available as `local-owner` without registration. Account workspaces are separate; signing in does not transfer local-owner boards. On Windows, `data/account-settings.json` and `data/account-sessions.json` are protected with DPAPI; other platforms use owner-readable files. These files are excluded from source exports and static serving. Email delivery, a real Supabase login, and live account deletion require the project's key and settings; automated tests use synthetic provider responses.

## Implemented services

| Area | What runs now | Configuration or practical limit |
| --- | --- | --- |
| Acquisition | Server RSS/Atom workers, a public-feed catalogue, mapped JSON connectors, CoinGecko and FRED adapters, conditional polling, bounded retries, Retry-After, durable job leases, dead-letter recovery, raw content-addressed storage, permitted document retrieval/import | The Sources directory shows measured availability and usable contributions. Configure provider credentials and permissions for licensed data; subscriptions are not included. |
| Verification | Sentence-level claim extraction; optional AI extraction with exact quote-span validation; candidate reporting chains; possible numerical/negation conflicts; explicit reviews; source revisions; correction/retraction propagation; additional high-consequence review | Detectors produce review candidates. They do not prove truth, independence, or authenticity. Hidden syndication still needs review. |
| Multilingual coverage | Original-language preservation, optional English translation, reviewed publisher geography, local-coverage gaps | Translation requires configured AI. Source geography and regions mentioned in text are separate metadata. |
| Trends | Hourly counts, coverage-adjusted windows, same-weekday/hour seasonal samples, robust MAD anomaly scores, lexical semantic clustering, optional vectors, persistent lifecycle history and periodic reassessment | Baselines require 95% uptime, a stable source set, and 70% provider availability across both windows. Seasonal scores need three covered historical samples. |
| Quantitative intelligence | Provider-timestamped observations, explicit asset namespaces, delayed-data flags, robust anomalies and return volatility, volume/liquidity warnings, transaction identity and chain-reorganization revisions | Mapped JSON connectors connect your licensed institutional/options/exchange/on-chain provider. Missing data is never replaced with fabricated prices. |
| Conversational research | Retrieval, persistent topic context, optional model synthesis, exact quote/document-ID checks, insufficient-evidence responses, retained research records | Configure a server API key and model for AI. Citation span checks establish traceability; logical interpretation still needs review. Prior answers are context, not evidence. |
| Knowledge graph | Namespaced entities, evidence-linked time-bounded relationships, inferred co-mentions, reviewed relationship records, traversal up to three hops | Co-mentions and downstream connections remain hypotheses unless reviewed. Entity aliases start with a small explicit set; bare tickers remain unresolved. |
| Autonomous intelligence | Follow-up collection from registered sources; disconfirmation questions; related-evidence retrieval; monitors/notifications; scheduled briefs; original scenarios and outcomes; descriptive Brier/reliability evaluation; source-version replay | Investigations search the collection and repoll registered sources. Arbitrary model URLs are never fetched. Evaluation is not prospective forecast calibration. |
| Reliability / governance | SQLite WAL or PostgreSQL, local raw objects or S3, worker failure isolation, Supabase accounts with private boards/portfolios, owner-only configuration, CSRF/origin/host checks, network restrictions, health and queue inspection, hash-chained audit records | Provider setup, external attestation, licensing, backups and distributed session storage need deployment-specific work. |

The original [feature blueprint](docs/FEATURE_BLUEPRINT.md) is retained as the broader design reference.

## Configuration

### Autonomous market research

The [autonomous research specification](docs/AUTONOMOUS_RESEARCH_SPEC.md) is retained alongside the original blueprint. A server worker now discovers explicit issuer/asset mentions against provider catalogues, collects filings and financial observations, computes metrics, maintains persistent asset profiles, applies watch-portfolio gates, investigates related events, and retains cross-market reports. Source ingestion, numerical revisions, claim reviews, documented exposures, and periodic freshness checks trigger reassessment. Leave `python CRAWLER/run.py` running for unattended operation.

The overview provides one-click profiles with the fourteen requested sections, an assessment revision selector, underlying source timestamps, calculation inputs, and “What changed?”. Watchlist contains six thematic portfolios, with one asset identity shared across themes. These are research lists: the application creates no purchases, weights, price targets, optimized allocations, or expected returns.

In **Sources & System → Autonomous asset research → Financial providers**, enable the providers you have configured:

| Connector | Server configuration | Collected evidence |
| --- | --- | --- |
| SEC discovery / `sec` | `SEC_USER_AGENT=YourApp contact@example.com` | Official issuer name/ticker/exchange/CIK associations, submissions metadata, and selected XBRL financial facts. Discovery registers issuer collectors from explicit mentions; a configured issuer source can use `{"cik":"0000320193","ticker":"AAPL","exchange":"NASDAQ"}`. |
| FRED vintages / `fred_vintages` | `FRED_API_KEY` | Observation dates, units, frequency, seasonal adjustment, real-time/vintage intervals, original and revised releases. Configure one series or a bundle of up to four. Bounded responses declare truncation. |
| Digital assets / `coingecko_asset` | `COINGECKO_API_KEY` for autonomous discovery | Provider identities and chain/contract mappings, actual price/supply/liquidity-related observations and daily price/volume history. Configure `{"id":"bitcoin","historyDays":90}` for direct collection. |
| Licensed market / `json` | Your provider endpoint, permissions, server credential environment variable and field mapping | Namespaced equity prices and other authorized measurements. No equity-price subscription is bundled. |

Provider interfaces follow the official [SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [FRED observation documentation](https://fred.stlouisfed.org/docs/api/fred/series_observations.html), and [CoinGecko history documentation](https://docs.coingecko.com/reference/coins-id-market-chart). SEC filing entries describe submission metadata; their presence does not mean the full filing narrative was analyzed. Missing or incompatible facts remain “Data unavailable”. Historical provider downloads establish availability when this application retrieved them, rather than proving what it knew before collection.

Qualification requires a provider-verified instrument identity, a positive current price from an enabled primary data source, a supported research trigger, the configured local observation period, and no unresolved contradictory/revised evidence. Default gates require seven days of observation, a price no older than 24 hours, and a trigger within 30 days. Rules are configurable in the same system view. Assets move through Under investigation → Qualified for monitoring → Continued monitoring; failing gates cause Review required, then Removed after the configured grace period. Financial profiles can exist before qualification. Portfolio summaries expose classification gaps, documented shared exposures, and aligned return correlations where sufficient comparable history exists.

Calculations retain formulas, input records/IDs, units, period and adjustment methodology. Same-period financial ratios and reported growth require compatible currency, accounting basis, periods and sources. Raw equity prices cannot produce adjusted-return comparisons. Explicit raw crypto histories carry unadjusted-price limitations. Historical volatility, threshold replay, benchmark comparisons and event studies describe observed samples; they do not establish causation or future returns. Event studies bind their chronology to a collected document's supported publication/event timestamp.

Exposure links require recorded review and source references. A source correction invalidates confirmed exposure links until reviewed again. Profile tools record policy maturity separately (statement, proposal, passage, enacted law, proposed/final rule, contract, opinion), jurisdiction, event date and effective date where applicable. Proposals are never automatically promoted to enacted policy. Coverage, financial freshness and contradictory reviews can withhold portfolio inclusion.

With `OPENAI_API_KEY`, `OPENAI_MODEL` and explicit `CRAWLER_AUTO_AI=true`, changed profiles queue bounded Responses API investigations using thirteen application-controlled read-only tools. The model may retrieve local canonical evidence and independently calculated metrics, propose follow-up questions, and return structured assessments. It cannot write facts, approve identities, confirm relationships, or override portfolio gates. Published findings must be exact source extracts with validated IDs and spans; proposed interpretations remain unpublished pending review. Financial/source changes during a model request invalidate its assessment. This follows the official [function-calling](https://developers.openai.com/api/docs/guides/function-calling) and [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) interfaces.

Current boundaries: general asset investigations repoll registered sources; saved topic research additionally supports bounded AI web discovery and permitted original-page retrieval. Broad global coverage, specialized licensed datasets, automatic legal interpretation, arbitrary filing-table extraction, and independently verified corporate exposure networks require appropriate providers and review. Provider credentials are not provisioned by this change. No live SEC, FRED, CoinGecko or paid AI request is claimed as validated by fixture tests. Revisions are durable within the configured database; backups and independently attested archives remain deployment responsibilities.

Copy `.env.example` to `.env` inside `CRAWLER`. Existing environment variables take precedence. `.env`, databases, raw objects, and Python caches are ignored by Git and blocked by the app's static-file server.

### AI research and translation

Click **Connect OpenAI** on the opening screen or topic results. Paste your API key, load the available models, select a **Research model** from the dropdown, and submit **Connect & start research**. A manual search or **Research again** uses the saved connection even when **Keep research running automatically** is unchecked. That checkbox controls background model calls between visits. Model choices come from the account's actual [OpenAI model list](https://developers.openai.com/api/reference/resources/models/methods/list). The server verifies the selected model with a bounded Responses request before saving or enabling background AI. A failed new connection leaves automatic work disabled; a failed replacement preserves the prior valid connection. Settings remain responsive during the check. Errors distinguish invalid keys, project permissions, model availability, API usage/billing limits, and timeouts. Use a model with structured output, function calling and web-search support for the full topic workflow; listing a model alone does not prove tool support.

Keys are sent only to the same-origin research server, stored outside application records in the ignored `data/openai-settings.json`, and protected for the current Windows user with DPAPI. Other operating systems use an owner-readable file. No key or key fragment appears in API responses, audit exports or browser storage. **Test connection** checks the saved connection; **Disconnect** disables AI and persistently overrides environment credentials. Saved keys are machine/user-bound on Windows and should not be copied to another installation. When using a remote server, use HTTPS and the server owner token.

The existing environment setup remains supported: set both `OPENAI_API_KEY` and `OPENAI_MODEL`; opt into automatic work with `CRAWLER_AUTO_AI=true`. Explicit settings saved through the app take precedence. `OPENAI_EMBEDDING_MODEL` defaults to `text-embedding-3-small`. Automatic planning, web searches, model investigations and enrichment can incur provider charges. The implementation follows the official [Responses web-search](https://developers.openai.com/api/docs/guides/tools-web-search), [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) and [embeddings](https://developers.openai.com/api/docs/guides/embeddings) interfaces.

For a topic, AI proposes a bounded search plan and synthesizes the collected source records into market research and connected watch subjects. The brief labels AI analysis and exposes the source passages supporting each finding. Citation checks establish traceability; they do not independently verify a publisher's claims or the model's interpretation. Optional web discovery uses actual web-search citations. At most four public HTTPS source pages per discovery pass are fetched after robots and network checks; only their original HTML/text becomes a collected record. Search snippets and model-written summaries never become evidence. Discovered pages retain an unverified claim status. Discovery is cached for an hour; unchanged evidence can reuse its prior report. New evidence mentioning a watched subject can trigger an earlier topic review. Financial measurements and instrument verification continue to require the configured data providers.

Without those settings, collection, deterministic extraction, retrieval, trends, graphs, monitors, briefs, replay, and manual review remain functional. Provider errors are explicit and failed jobs remain reviewable. Private API keys are never returned to the browser.

### Connectors

Use **Sources & System → Add connector** for RSS/Atom or JSON APIs. Sources can be enabled, paused, edited, or polled immediately. Record permissions, source family, language, publisher geography, and frequency. A credential field names a server environment variable rather than storing its value in the page.

Example generic quote mapping:

```json
{
  "itemsPath": "data",
  "recordType": "observation",
  "assetClass": "equity",
  "metric": "price_usd",
  "fields": {
    "assetId": "asset_id",
    "value": "price",
    "observedAt": "timestamp"
  }
}
```

Each provider row supplies an identity such as `equity:NASDAQ:NVDA` or a chain-qualified token identifier. A constant `assetId` can be configured for a single-asset endpoint. On-chain mappings may include `transactionHash`, `logIndex`, `blockHash`, and `removed`; liquidity analysis may include `liquidity` and `volume24h`.

For article records, use `recordType: "document"` with fields `title`, `text`, `url`, and `publishedAt`. Paths use dot notation, including array indexes. CoinGecko uses `COINGECKO_API_KEY` when configured; FRED requires `FRED_API_KEY`. Provider interfaces: [CoinGecko](https://docs.coingecko.com/reference/simple-price), [FRED](https://fred.stlouisfed.org/docs/api/fred/series_observations.html).

Feeds and permitted documents check robots.txt, public HTTPS destinations, response size, redirects, and host rate spacing. Full-document retrieval is disabled until enabled for a source. Network requests reject private, loopback, link-local, and reserved destinations and pin validated IPs during TLS connections. XML entity declarations are rejected. The legacy browser fallback can still use public CORS proxies; server collection does not use those proxies.

### Sources directory and efficient collection

Open **Sources** beside the search bar to search publishers, filter by content type or connection status, inspect collected headlines, add a public RSS/Atom feed, and queue collection. It loads on demand and renders twelve sources at a time. Connected sources appear first. The original centered search screen remains the default.

The catalogue includes all requested publishers: Flipboard, NPR, The New York Times, BBC, NBC, ProPublica, The Intercept, Democracy Now!, The Marshall Project, Inside Climate News, Reuters discovery, Business Insider, CNBC, Yahoo Finance, Bloomberg and Google News. Added reporting and analysis includes Bellingcat, ICIJ, 404 Media, Capital & Main, Global Voices, Grist, Al Jazeera, DW, France 24, Calculated Risk, Aswath Damodaran, Marginal Revolution, Ben Carlson, Nick Maggiulli, Noah Smith and Matt Stoller. Ipsos and Pew provide survey-research connections. Public finance discussions include RSS connections and the documented [Hacker News search API](https://hn.algolia.com/api).

Availability is measured, not assumed. See [the live connection report](docs/feed-connection-check.json) for the dated result of the collection run. Some endpoints deny automated access or have temporary failures. Those remain visible with their error and next retry time. The Yahoo endpoint was updated from its obsolete 404 URL, but its destination currently disallows collection. Reuters is explicitly a Google News discovery connection; direct Reuters delivery needs authorized provider access. These entries do not claim a working licensed feed.

Reporting, official releases, commentary and survey research carry their content role into AI topic synthesis. Discovery headlines and community discussions are stored separately as **research leads**; they do not create verified claims, factual relationship edges or prices. Relevant discovery links can enter the existing bounded original-page retrieval workflow. Community discussions can be inspected and opened directly. Survey headlines require their underlying methodology before interpreting them as population estimates. Private chats, login-only forums and subscriber-only text need an authorized connector. Numeric market observations remain with the existing instrument-aware financial connectors.

Collection now uses ETag/Last-Modified validators where supplied, recognizes HTTP 304, deduplicates unchanged entries before indexing, checks redirected feed permissions, isolates rejected entries, and records per-poll new/revised/unchanged/rejected counts and duration. Source endpoints and paused choices edited by the user are preserved when catalogue updates are installed. Known obsolete default endpoints are repaired. Legacy HTTP article links are upgraded only for the configured Democracy Now! and Calculated Risk hosts, preserving the publisher-supplied URL in raw metadata.

Polling requests coalesce into one queued job per source and respect provider cooldowns. With the default two workers, one is reserved for topic/board research and the other processes collection and background analysis. `CRAWLER_WORKERS=4` allows three background workers. Host spacing and bounded retries remain active. Initial archive collection can take several minutes; subsequent unchanged polls avoid indexing and analysis work. Browser archive synchronization uses at most two 100-document pages per pass and yields while processing. No archive or feed directory requests run on the idle search screen.

Run a repeatable connection check without storing articles:

```powershell
python CRAWLER/tools/poll_sources.py --report CRAWLER/data/feed-check.json
```

Collect into the application's database without starting AI workers:

```powershell
python CRAWLER/tools/poll_sources.py --collect --report CRAWLER/data/feed-check.json
# Optional: limit a check or collection to particular source IDs
python CRAWLER/tools/poll_sources.py --collect --source bbc-business --source hn-api
```

Use `--data-dir` for a separate SQLite archive; an already-set `DATABASE_URL` selects PostgreSQL. The command does not load `.env` or schedule paid enrichment. For configured/credentialed connectors, use the running server's **Poll enabled sources** action. Read `/api/source-items?id=…` for bounded contribution previews; owner-only POST `/api/sources/poll-all` queues enabled sources without waiting for remote requests.

### Database and raw objects

`CRAWLER/data/` contains the default `research.sqlite3` and content-addressed raw objects. Source versions are append-only. Back up both together.

For PostgreSQL, install `psycopg[binary]`, set `DATABASE_URL`, and restart. For S3-compatible storage, install `boto3` and configure `S3_BUCKET`, AWS credentials, and optionally `S3_ENDPOINT_URL`. Existing data is not automatically migrated. These adapters require an available service and credentials before they can be exercised.

Install only needed adapters from `requirements-optional.txt`. PDF extraction requires `pypdf`; encrypted PDFs and PDFs over 100 pages are rejected. Media imports preserve the binary and SHA-256 digest. `C2PA_TOOL` optionally names an installed validator executable, invoked without a shell. Provenance and valid credentials do not establish whether depicted content is true.

### Access and deployment

The default loopback binding trusts the local owner. Another interface requires `CRAWLER_AUTH_TOKEN`; set `CRAWLER_ALLOWED_HOSTS` to the intended hostname and use an HTTPS reverse proxy. The owner token controls system administration. Supabase accounts access their own boards/portfolios and shared source evidence. Browser sign-in creates an HttpOnly same-site session cookie and CSRF token. Owner API clients may use `Authorization: Bearer <owner token>`. Remote users should reach the HTTPS proxy, with its trusted forwarded-protocol header, rather than the development HTTP port. Session storage currently supports one server process; distributed deployments need shared session infrastructure.

Monitors create in-app notifications. Scheduled briefs are stored in Watchlist. Neither sends email, chat messages, nor webhooks. Scenario statements and assumptions cannot be edited through outcome endpoints. The audit hash chain detects ordinary edits; an administrator controlling the database can rewrite a chain, so it is not independent attestation.

Replay selects the latest source version retrieved by the requested time and applies only enrichment/review state then available. Replay and analytical queries are bounded to 20,000 records per collection. Large archives need indexed search and partitioned analytical storage.

## API

Read routes: `/api/health`, `/api/session`, `/api/sources`, `/api/documents`, `/api/events`, `/api/dossier`, `/api/graph`, `/api/workspace`, `/api/operations`, `/api/metrics`, `/api/replay`, `/api/document-versions`, `/api/raw`, `/api/export`.

Asset routes: `/api/investment`, `/api/asset-profile?id=…&at=…`, `/api/cross-market-report?id=…&at=…`, `/api/asset-assessments?id=…`, `/api/observations?assetId=…&at=…`, `/api/event-study?assetId=…&benchmarkId=…&documentId=…`. POST `/api/investment/rules`, `/api/investment/run`, `/api/investment/discover`, `/api/policy-records`. Profile revisions, original observation vintages and report revisions are included in the audit export.

Topic routes: GET `/api/topics` and `/api/topics?id=…`; POST `/api/topics` with `{query}`, `/api/topics/refresh` with `{id}`, and `/api/topics/toggle` with `{id,enabled}`. Account users see only topics they follow; pausing an account topic pauses its notifications without stopping shared collection for other users. Topic revisions are included in the owner audit export. OpenAI routes: GET/POST `/api/ai/settings`, GET/POST `/api/ai/models`, POST `/api/ai/connect` (verify then save), and POST `/api/ai/test`. Credential changes and model-list access require the owner; accounts can read sanitized connection status. `/api/ready` provides a lightweight startup check without waiting for archive queries.

Private research routes: GET/POST `/api/boards`, POST `/api/boards/save` with `{id,baseVersion,…}`, POST `/api/boards/action`, GET `/api/network-node?boardId=…&id=…`, POST `/api/network/research`, POST `/api/portfolios`, GET/POST `/api/my-research`, and GET `/api/my-research/export`. Conflicting layout saves return HTTP 409. Canonical relationship review uses owner-only POST `/api/network/review`. Personal assertions cannot be promoted through save APIs.

Account routes: GET `/api/accounts`; POST `/api/accounts/setup` (owner only), `/login`, `/register`, `/recover`, `/resend`, `/verify`, `/callback`, `/profile`, `/password`, `/reauthenticate`, `/logout`, `/revoke-session`, `/mfa-enroll`, `/mfa-challenge`, `/mfa-verify`, `/mfa-remove`, and `/delete`, each under `/api/accounts/`. Password/token values are not included in returned account state.

JSON mutation routes cover sources, document import/fetch/enrichment, claim reviews, questions, investigations, relationships, monitors, scenarios/outcomes, brief schedules, saved work, observations, and dead-letter retries. They require an owner session plus `X-Crawler-CSRF`, or an authorized bearer token. The UI manages its own session tokens.

## Tests

From `HTML Tests`:

```powershell
python -m unittest discover -s CRAWLER/tests -p 'test_*.py' -v
node --test CRAWLER/tests/research.test.cjs
```

Browser tests use an existing `playwright-core` installation and Chrome. Set `PLAYWRIGHT_MODULE` to its path if needed:

```powershell
node CRAWLER/tests/browser-smoke.cjs
node CRAWLER/tests/server-browser.cjs
node CRAWLER/tests/investment-browser.cjs
node CRAWLER/tests/search-browser.cjs
node CRAWLER/tests/loading-browser.cjs
node CRAWLER/tests/market-research-browser.cjs
node CRAWLER/tests/network-browser.cjs
node CRAWLER/tests/sources-browser.cjs
```

The first starts a static server and checks fallback, navigation, review gates, local persistence, search, exports, and responsive layout. The second starts an isolated fixture research server and checks sync, extracted/reviewed claims, citations, monitors, briefs, connectors, replay, and revision deduplication. The market research suite checks a manual connected-model search with background AI off, a cited market brief and three types of watch subjects despite no financial instrument qualification, refreshes and mobile layout. Fixtures never enter the real application database. External providers are blocked during browser tests. Live AI, PostgreSQL, S3, licensed data, PDF, and C2PA adapters need configured integration environments.

Network tests cover entity/relationship citation checks, missing/negated supplier evidence, bylines, review invalidation, source updates, private ownership, exact layout persistence, manual assertion isolation, revisions and bounded tasks. Account tests cover provider contracts, token storage, CSRF rotation, MFA authorization and cross-account denial. The board browser test exercises canvas gestures, group/undo/redo, save/reopen, focused research, responsive layout, account forms and workspace separation.
