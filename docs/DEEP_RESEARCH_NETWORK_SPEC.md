# Deep Research Network — Expanded Application Specification

The application should now focus on investigative relationship mapping, rather than simply discovering market trends or recommending stocks.

When a user searches for a subject such as “Drones,” the AI should autonomously investigate everything demonstrably connected to that subject: news coverage, manufacturers, company ownership, financial statements, investors, related businesses, public contracts, suppliers, competing companies, and financial institutions.

The results should appear on an interactive observation board, with the original research topic at its center and expandable chains of verified relationships extending outward.

The user should be able to explore those chains, add independent observations, create custom connections, and save the entire investigation to a personal account.

## A real example from your drone story

I verified several useful starting points for the application.

- The exact headline you supplied appears in BBC coverage dated October 19, 2026. The accessible listing identifies BBC as the publisher, but I could not establish an individual byline for that specific BBC video.&#x20;

  [image](https://www.google.com/s2/favicons?domain=https://www.globalsconflicts.com\&sz=32)

  BBC World

- Separate reporting by Jake Epstein of Business Insider identifies the aircraft as the Heavy Shot AYUDAG 6, manufactured by Gurzuf Defence. That author belongs to the Business Insider article, not necessarily the BBC report.&#x20;

  [image](https://www.google.com/s2/favicons?domain=https://www.businessinsider.com\&sz=32)

  Business Insider

- Ukrainian company-registry aggregators identify Gurzuf Defence under registration number 44825049, with three listed owners and published financial information.&#x20;

  [image](https://www.google.com/s2/favicons?domain=https://opendatabot.ua\&sz=32)

  ТОВ ГУРЗУФ ДЕФЕНС

  +1

- Public company records also connect one of its owners, Pavlo Feldblium, to Gurzuf Electronics and Gurzuf Energy. This establishes corporate-person relationships, not necessarily direct supply contracts between those companies.&#x20;

  [image](https://www.google.com/s2/favicons?domain=https://opendatabot.ua\&sz=32)

  компанії, ФОП, посади



This demonstrates the distinction your application needs to preserve: an article can lead to a real manufacturer, that manufacturer to verified owners, and those owners to other companies. But each connection must have its own supporting evidence.

For instance, Gurzuf Defence is a registered limited-liability company, not an established publicly traded stock in the records reviewed. Your application should therefore classify it as a private-company research subject, rather than inventing a ticker or stock price.

## How the observation board should work

The investigation must be a navigable graph, not a static flowchart.

Example research network — verified connections and unanswered questions

[Exported diagram styles omitted; the surrounding text describes the intended relationships.]

The ownership connection does not establish a supplier relationship. Dotted connections represent unanswered research questions, not confirmed relationships.

Each bubble should be a separate interactive research object. Clicking one opens a detailed panel; double-clicking expands related entities; dragging a connector to empty canvas space creates a new linked bubble.

### Essential graph interactions

| User action                        | Application behavior                                                  |
| ---------------------------------- | --------------------------------------------------------------------- |
| Click a bubble                     | Open supporting evidence, financial information, and research details |
| Double-click a bubble              | Expand its verified relationships                                     |
| Drag a connection into empty space | Create a user-defined node and link                                   |
| Drag between two existing bubbles  | Propose a relationship and select its type                            |
| Click a connecting line            | View why the entities are linked and inspect evidence                 |
| Right-click a bubble               | Edit, annotate, duplicate, hide, pin, or initiate deeper AI research  |
| Select multiple bubbles            | Group into a named branch or research collection                      |
| Collapse a branch                  | Hide secondary connections without deleting underlying data           |
| Save the board                     | Persist nodes, edges, positions, notes, and research settings         |
| Reopen the board                   | Restore the exact saved layout and continue investigation             |

User-created nodes must remain visibly separate from AI-verified data. Manually adding a connection must never cause the AI to consider that relationship established.

### Research controls

Add Research Further to every node. For example, selecting Gurzuf Defence should let the user initiate focused investigations into its ownership, finances, public contracts, production, related businesses, competitors, or publicly disclosed supply relationships.

The AI should be able to expand additional levels automatically, but must avoid flooding the board with loosely related entities. Prioritize direct, documented connections and progressively expand deeper branches when they are relevant.

## Copy-ready implementation specification

The following instructions are intended to extend your existing application's research engine, rather than replace the features already implemented.

# Research Network Intelligence — Feature Expansion

## Primary Development Objective

Expand the existing autonomous research application into a comprehensive, interactive investigative intelligence platform.

The application must trace relationships between topics, news articles, journalists, companies, investors, executives, financial institutions, ownership structures, government contracts, manufacturers, suppliers, competitors, and relevant financial markets.

The primary interface will be an interactive, persistent **Research Observation Board** displaying the relationships between these entities through connected nodes and expandable branches.

Retain all existing market research, news aggregation, source verification, OpenAI integration, asset monitoring, and portfolio features.

Do not replace the existing research engine. Build the following capabilities on top of it.

## 1. Topic-Based Autonomous Investigation

When a user searches a topic, the application must perform progressively deeper investigations rather than simply returning search results.

Example search: **Drones**

The system should:

1. Retrieve relevant news articles from indexed sources and perform additional searches where necessary.
2. Group articles referring to the same event without losing their individual authors or publishers.
3. Identify named manufacturers, companies, products, financial institutions, government agencies, and individuals.
4. Investigate verified relationships between those entities.
5. Retrieve relevant company registration and financial information.
6. Identify additional companies through documented ownership, corporate partnerships, contracts, and investment relationships.
7. Investigate related industries, publicly disclosed suppliers, and competitors.
8. Identify publicly traded companies or financial instruments associated with the resulting research.
9. Build a structured relationship graph connecting verified findings.
10. Continue research when new evidence or significant developments appear.

Every connection must be substantiated by actual evidence.

The system must not automatically assume relationships merely because entities occur in the same article or industry.

## 2. Article and Journalist Investigations

Every article node must provide:

- Original headline.
- Publication name.
- Original article URL.
- Author or authors, when confirmed.
- Publication date and update history.
- Original reporting versus republished or syndicated material.
- Factual claims extracted from the article.
- Independent corroborating or contradictory sources.
- Corrections or retractions.
- Companies, people, industries, and events mentioned.
- References to primary-source documentation.

### Journalist Research

When an author is identified, create a separate journalist node containing verifiable professional information and published work.

The AI should examine:

- Previous reporting on related subjects.
- Subjects and organizations frequently covered.
- Documented differences in framing across coverage.
- Use of primary versus secondary information.
- Published corrections or material factual inaccuracies.
- Disclosed affiliations or conflicts of interest relevant to the reporting.
- Patterns of factual consistency or contradiction across comparable reporting.

Do not assign political beliefs, motives, personal affiliations, or subjective bias labels based only on article topics, tone, or the AI's interpretation.

If the system identifies a potentially relevant reporting pattern, it must show concrete examples and supporting sources.

Distinguish measurable editorial framing from unsupported allegations about a journalist.

## 3. Corporate Relationship Investigations

When a company is discovered, automatically investigate its publicly documented corporate structure.

### Company identity

Retrieve:

- Registered legal name and alternative trade names.
- Jurisdiction and registration number.
- Company operating status.
- Industry classifications.
- Products and services.
- Publicly traded or privately held status.
- Verified exchange and ticker information, where applicable.

### Ownership

Research and establish:

- Parent companies.
- Subsidiaries.
- Shareholders and beneficial owners where publicly disclosed.
- Directors and corporate officers.
- Joint ventures.
- Ownership percentages and applicable dates.
- Other companies connected through documented ownership or control.

Represent each person and company as a separate graph entity.

A person owning shares in two businesses establishes a common-owner connection. It does not independently prove those businesses trade with, fund, or supply one another.

### Corporate partnerships

Investigate publicly disclosed partnerships, acquisition transactions, licensing arrangements, strategic investments, and joint ventures.

Each relationship must preserve its exact nature.

An announced collaboration must not be presented as an ownership relationship.

A customer-supplier arrangement must not automatically be presented as a strategic partnership.

## 4. Financial Structure Investigations

Every relevant company should have a dedicated financial research panel.

Retrieve available financial statements and corporate disclosures.

Analyze:

- Revenue and revenue changes.
- Gross and net profit.
- Operating margins.
- Assets and liabilities.
- Debt.
- Equity.
- Operating cash flow.
- Capital expenditure.
- Funding rounds and investments.
- Publicly disclosed lending relationships.
- Parent/subsidiary financial consolidation.
- Major disclosed customers.
- Government procurement revenue where verifiable.

Financial data should be displayed using the original reporting currency and stated reporting period.

All calculations must be based on retrieved figures and deterministic application calculations.

### Financial institution connections

Identify financial institutions only when a documented relationship exists, such as:

- Disclosed corporate lending.
- Debt underwriting.
- Equity ownership.
- Financing arrangements.
- Publicly reported investment participation.
- Confirmed financial advisory relationships.

Do not infer that a company uses a particular bank merely because that bank operates in the same industry or country.

Financial institutions should become expandable research nodes with their own company profiles, ownership information, related disclosures, and relevant publicly traded instruments.

## 5. Government Contract and Procurement Research

Search public procurement records and officially disclosed contract information.

Where available, show:

- Contracting organization.
- Contract recipient.
- Public award date.
- Original contract value and currency.
- Contract category and product description.
- Contract status.
- Public amendments.
- Original procurement reference.

Distinguish tenders, announced awards, signed contracts, and completed transactions.

Do not interpret the full value of a multi-item procurement contract as the price of a single piece of equipment.

For active military systems, restrict supply-chain visualization to appropriately public, non-operational commercial information. Do not expose sensitive logistics, restricted manufacturing details, or operational deployment information.

## 6. Manufacturing and Supply-Chain Research

The AI must trace a company's documented manufacturing and commercial supply relationships.

The research may include:

- Publicly disclosed component suppliers.
- Material categories.
- Known manufacturing partners.
- Published supply agreements.
- Public country-level manufacturing or sourcing information.
- Financial exposure to material costs.
- Reported supply constraints.
- Publicly available product and procurement pricing.
- Industry dependency on particular materials or technologies.

The application must not construct a specific supplier relationship from general industry knowledge.

For example, identifying a company as a producer of drone motors does not establish that it supplies motors to a particular drone manufacturer.

Unverified potential connections must remain separate research questions.

### Asset pricing

Distinguish:

- Public list price.
- Contract award price.
- Average disclosed procurement price.
- Financially reported unit cost.
- Market price of a publicly traded financial instrument.

Do not substitute one for another.

If the price is undisclosed, indicate that information is unavailable.

## 7. Competitor and Alternative Manufacturer Research

Identify companies producing competing or substitutable products using documented product information.

The AI should compare:

- Products and intended markets.
- Public technical specifications.
- Published pricing where available.
- Financial scale.
- Revenue growth.
- Corporate ownership.
- Public contracts.
- Geographic markets.
- Relevant regulatory exposure.
- Publicly traded status.

Classify the relationships accurately:

**Direct competitor:** Produces a comparable product targeting a similar market.

**Adjacent competitor:** Participates in a related market with partial product overlap.

**Alternative supplier:** Offers products within a related supply category without necessarily competing directly.

**Related industry participant:** Has a broader economic or technological relationship to the topic.

The AI should avoid speculative rankings when comparable financial or product data is unavailable.

## 8. Interactive Research Observation Board

Create an infinitely pannable and zoomable research canvas.

The starting topic must occupy the root position, with linked research findings extending outward in organized branches.

### Node categories

Support nodes for:

- Research topics.
- News articles.
- Authors and journalists.
- Events.
- Companies.
- Products and technologies.
- Owners and executives.
- Financial institutions.
- Financial records.
- Government contracts.
- Regulators and government agencies.
- Suppliers.
- Materials.
- Manufacturing regions.
- Competitors.
- Stocks and financial instruments.
- User-defined observations.
- Unanswered research questions.

Use consistent visual distinctions for different node categories.

### Node inspection

Selecting a node opens a details panel containing:

- Entity name and category.
- Summary of established information.
- Relevant dates.
- Source references.
- Financial data, when applicable.
- Evidence status.
- Existing connections.
- Notes and annotations.
- Research history.
- Actions for expanding the investigation.

### Editable graph connections

Users must be able to:

- Drag nodes to reposition them.
- Connect any two nodes through a drag gesture.
- Drag a connector into empty space to create a new information bubble.
- Edit relationship descriptions.
- Change relationship types.
- Annotate individual connections.
- Delete personal connections.
- Group selected nodes.
- Collapse or expand branches.
- Pin important nodes.
- Search and filter the visible network.
- Undo and redo actions.

User-generated connections must be saved as manual research assertions rather than verified system facts.

Allow users to attach citations and request AI verification.

The AI must not promote a manually created claim to verified status without independent evidence validation.

### Connection classifications

Use explicit relationship types such as:

- Authored by.
- Published by.
- Reports on.
- Manufactured by.
- Owned by.
- Subsidiary of.
- Partnered with.
- Invested in.
- Financed by.
- Contract awarded to.
- Supplied by.
- Competes with.
- Produces.
- Associated through common ownership.
- References.
- Research question.
- User-defined relationship.

Do not use a generic connection type when the precise relationship can be established.

### Visual evidence indicators

Use different line treatments for:

- Verified relationships.
- Corroborated relationships.
- Developing or disputed relationships.
- Unanswered research questions.
- User-created relationships.

Show the evidence and current status when a user clicks a connection.

Each relationship should include the observation date and the date on which it was last verified.

## 9. Autonomous Graph Expansion

The AI must be able to investigate individual nodes or entire branches.

Implement options for:

- Research this entity.
- Investigate ownership.
- Find associated companies.
- Investigate financial structure.
- Find disclosed contracts.
- Explore competitors.
- Explore documented supply relationships.
- Find related publicly traded assets.
- Verify selected connection.
- Find contradictory evidence.
- Expand entire branch.

The AI should expand research progressively.

Do not load the entire possible relationship network simultaneously.

Use relevance, verified connectivity, user focus, and research depth to determine the order of expansion.

Maintain a research queue so complex investigations can resume after interruptions and avoid repeatedly searching identical questions without reason.

The user should be able to pause, resume, or cancel autonomous expansion.

## 10. Financial Watchlist and Portfolio Integration

Connect the graph system to the application's existing market research and portfolio functionality.

Users must be able to select a company, financial institution, or publicly traded instrument and choose:

**Add to Watch Portfolio**

For public securities, the system should retrieve verified market data and maintain the financial profile.

For private companies, maintain a corporate monitoring profile without fabricating a market price or ticker.

Support thematic portfolios containing combinations of:

- Public companies.
- Private companies.
- Financial institutions.
- Industries.
- Technologies.
- Commodities.
- Financial instruments.
- Research topics.

Portfolios should preserve the reasons why each item was added and which graph relationships are relevant.

When new developments are discovered, the application must identify affected portfolios and update their research status.

## 11. User Registration, Login, and Account Management

Implement a complete authentication system backed by a persistent database.

### Authentication pages

Create dedicated pages for:

**Login**

- Email and password.
- Remember session.
- Forgot password.
- Link to registration.

**Create Account**

- Display name.
- Email.
- Password.
- Password confirmation.
- Terms acceptance where applicable.
- Email verification.

**Account Management**

- Edit profile.
- Change password.
- Manage active sessions.
- Security settings.
- Export personal research data.
- Delete account and associated private data.

Use a mature authentication provider or audited authentication library.

Passwords must never be stored in plaintext.

Implement secure session management, email verification, password reset, rate limiting, and authorization checks.

Offer multifactor authentication when supported.

### User-owned research

Every registered user must have a private research workspace.

The workspace must contain:

- Saved research boards.
- Saved node positions and layouts.
- Custom relationships.
- Manual observations.
- Annotations.
- Saved company profiles.
- Watch portfolios.
- Followed topics.
- Research history.
- Notification settings.

All personal research must persist between sessions and devices.

Users must not gain unauthorized access to another user's private boards or portfolios.

## 12. Research Portfolio Management

Create a **My Research** dashboard accessible after login.

Users should be able to:

- Create new research portfolios.
- Rename and describe portfolios.
- Organize portfolios into folders.
- Save existing observation boards.
- Duplicate research boards.
- Resume previous investigations.
- Add or remove watched entities.
- Manually annotate findings.
- Export research to suitable formats.
- Review changes since their last session.
- Archive or delete portfolios.
- Restore previous research revisions where available.

Each saved portfolio should retain a reference to the underlying graph data.

Reopening a board must restore its structure, node positions, manually created connections, annotations, and expansion state.

### Shared research data versus private edits

Maintain a canonical database of verified public research entities.

Maintain user-specific graph layouts, annotations, manual connections, and portfolio selections separately.

This allows multiple users to research the same company without duplicating all verified source records.

A user's edits must not alter canonical evidence or other users' private research.

When public research data changes, update relevant user portfolios without destroying personalized layouts or annotations.

## 13. Evidence and Provenance Requirements

Every AI-generated factual node and connection must include:

- Unique entity or relationship identifier.
- Supporting source identifiers.
- Original source URLs.
- Publication and retrieval dates.
- Exact claim or observation supported.
- Verification status.
- Relevant reporting period.
- Last validation timestamp.

Unverified information must not be silently displayed as fact.

If research is inconclusive, the AI should create an **Unresolved Research Question** node identifying the missing evidence.

The system must distinguish:

1. Established facts.
2. Reported claims.
3. Analytical interpretations.
4. Hypotheses requiring investigation.
5. User-provided assertions.

Never treat a language model's previous output as an independent factual source.

## 14. OpenAI Integration

Use the existing OpenAI integration as the research coordinator.

The AI must be able to:

- Investigate newly discovered entities.
- Select appropriate retrieval tools.
- Extract claims and relationships.
- Resolve entity identities.
- Request financial and corporate records.
- Compare sources.
- Identify evidence gaps.
- Propose additional investigations.
- Generate structured graph node and relationship records.
- Explain how entities are connected.
- Reassess findings when new evidence is published.

All financial calculations must continue to use verified data and deterministic code.

Use structured function calls and validated output schemas.

The AI must not insert unsupported entities, links, financial figures, or relationship assertions into the verified graph.

## 15. Data Model

Extend the existing database with the following entities where needed:

- `users`
- `research_workspaces`
- `research_topics`
- `research_boards`
- `research_nodes`
- `research_edges`
- `entity_records`
- `entity_aliases`
- `evidence_records`
- `relationship_evidence`
- `financial_observations`
- `source_documents`
- `research_tasks`
- `research_annotations`
- `portfolio_items`
- `portfolio_watch_conditions`
- `research_versions`
- `research_notifications`

Use stable identifiers so the same company can appear in multiple research boards without being mistaken for a different entity.

Represent relationship direction, relationship type, start and end dates, and supporting evidence explicitly.

Maintain revision history rather than destructively overwriting past research.

## 16. User Interface Requirements

The primary application layout should include:

**Left sidebar**

- Research search.
- Recent investigations.
- My Research.
- Saved portfolios.
- Followed companies.
- Notifications.

**Center workspace**

- Interactive research graph.
- Draggable and expandable nodes.
- Connected research branches.
- Zoom controls.
- Mini-map.
- Research progress indicators.

**Right sidebar**

- Selected entity information.
- Financial records.
- Evidence citations.
- Related entities.
- Research controls.
- Personal notes.

**Top toolbar**

- Save board.
- Research further.
- Add node.
- Auto-arrange.
- Filter connections.
- Undo/redo.
- Export.
- Account menu.

Keep the interface responsive, readable, and suitable for very large research graphs.

Use node clustering, progressive loading, and efficient graph rendering rather than displaying thousands of connections simultaneously.

## 17. Required Acceptance Tests

The implementation is complete only when:

1. Searching "Drones" retrieves relevant indexed articles, including the supplied Ukraine drone-evacuation story when the source is available.
2. The system preserves the correct publisher and author attribution for each distinct article.
3. The AI identifies the drone manufacturer from supporting evidence.
4. The manufacturer links to verified corporate records.
5. Relevant disclosed financial information is displayed with correct dates, amounts, and currencies.
6. Public owners and other company interests appear as distinct nodes with documented relationships.
7. Related companies are not automatically labeled as suppliers or partners without evidence.
8. Public contracts are linked to the correct legal entity and contracting organization.
9. Unavailable supplier, manufacturing, or pricing information is clearly marked as unavailable.
10. Users can add their own nodes and drag connections between them.
11. User-created links remain distinguishable from verified connections.
12. The user can save an investigation, log out, log back in, and restore the full board.
13. Research portfolios persist and remain private to their owners.
14. Additional verified findings update affected research without removing user annotations.
15. The AI can continue investigating branches autonomously while respecting source reliability and research-depth limits.
16. No fabricated ticker, price, financial metric, corporate relationship, or evidence citation appears in the research results.

## Final Implementation Requirement

The application should behave like an autonomous financial and corporate investigative analyst with a visual relationship-mapping interface.

Its job is not merely to answer what a news article says.

It must investigate who and what is connected to the event, which financial and corporate relationships can be verified, how those entities relate to publicly observable markets, and what additional developments warrant monitoring.

Users must be able to participate in that investigation by creating, editing, arranging, and saving their own connected research networks.

**Every verified connection must have evidence. Every unsupported connection must remain explicitly unverified.**

## Recommended implementation technologies

For the graph interface, [React Flow](https://reactflow.dev/?utm_source=chatgpt.com) is particularly suitable. It supports draggable nodes, custom connection handles, editable graph relationships, and diagram save/restore operations.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://reactflow.dev\&sz=32)

React Flow

+1



For account management, [Supabase Auth](https://supabase.com/docs/guides/auth?utm_source=chatgpt.com) combined with PostgreSQL row-level security is a practical option if the existing application does not already have authentication. It supports registration, email/password sign-in, session management, and database-level access restrictions.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://supabase.com\&sz=32)

Supabase Docs

+1



The existing [OpenAI Responses API](https://developers.openai.com/api/reference/responses/overview?utm_source=chatgpt.com) integration can coordinate the investigations through function calling and structured outputs.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://developers.openai.com\&sz=32)

OpenAI API Reference

+1



The most important architectural decision: Make the underlying research graph a persistent, evidence-backed database. The visual board should be an editable view of that database, not the place where the AI's conclusions are stored as unverified text.

This is what will allow the application to support long-running investigations, shared verified data, private user annotations, automatic updates, and saved research portfolios without compromising the integrity of its findings.
