# Construction Demand Readiness Investigator

This is the public preparation kit. Environment-specific identifiers were replaced with placeholders. Resolve source IDs from **your own** ignored deployment manifest after deployment. The included validation results are synthetic reference answer keys, not access to a shared live service or proof that your data agent has been tested.

## Recommendation

**Business question: "Before we restart marketing, which customer promises could we make harder to keep?"**

Use a Fabric data agent as the **evidence investigator upstream of the 3IQ decision workflow**. It discovers connected exposure, reconciles the numbers, and checks observed events and consent. It does not repeat the command center's job of combining institutional policy, collaboration context and human-approved actions.

**Status:** preparation only. No Fabric data-agent item was created, published, invoked or modified. The workspace and its data were inspected read-only. All **12 source-native example queries were executed successfully against the existing live sources**: five GQL, four T-SQL and three KQL. This verifies the examples and answer key, not a future data agent's natural-language routing or generated answers.

### The one-minute story

> "Marketing sees interest in insulation for a school renovation. That sounds like a good opportunity. But the material is already shared by a school, apartments and an office refurbishment. We need to find the connected commitments, measure the actual gap, and distinguish a stock problem from a consent problem before asking the 3IQ command center what to do."

Three discoveries make the story concrete:

1. **One campaign can touch customers other than its originating account.** A nine-edge path from one customer profile reaches Birch and Cedar, whose commitments share the constrained material.
2. **Alternative material is not necessarily spare material.** The board proposed as a candidate for Elm has its own 24 existing commitments: 6,200 m2 ordered against 4,030 m2 available.
3. **Availability is not permission.** Juniper's current proposal fully covers 350 m2, yet its construction-marketing consent is denied.

The finish is an evidence brief, not "the agent automatically restarted the campaign."

### How it complements the 3IQ app

| Fabric data agent: investigate | Existing 3IQ command center: decide with governance |
| --- | --- |
| Start from a signal, campaign, profile or material rather than a selected queue record | Start from an exposed commitment and coordinate the next decision |
| Discover indirect dependencies and affected peers through actual GQL paths | Combine structured evidence, institutional policy and synthetic Work IQ context |
| Reconcile quantities, values, timestamps and consent using each source's native query language | Explain permitted actions, owners, approval checkpoints and customer-safe drafts |
| Return a compact, cited factual handoff | Prepare an approval-required action package |

Both remain read-only in this demo. The existing app does not automatically call this future data agent; no new integration was built.

## Connect exactly these three existing sources

Workspace: `Construction 3IQ Demo` in your own tenant. Find its ID and selected existing F32 in your local deployment manifest.

Proposed future agent name: **Construction Demand Readiness Investigator**.

| Logical role | Existing source to choose | Item ID | Native query |
| --- | --- | --- | --- |
| Graph: connected exposure | `ConstructionSupplyOntology_graph_ONTOLOGY_ID` | `<GRAPH_MODEL_ID>` | GQL |
| Lakehouse: exact arithmetic | `ConstructionSupplyLakehouse` | `<LAKEHOUSE_ID>` | T-SQL through its SQL analytics endpoint |
| Events: observed activity | **`ConstructionSupplyEvents`**, inside `ConstructionSupplyEventhouse` | `<KQL_DATABASE_ID>` | KQL |

Obtain the Lakehouse SQL endpoint ID from your deployed Lakehouse properties. Connect the Lakehouse source through the data-agent UI; do not manually create an endpoint.

### Important source-selection distinctions

- Add the **GraphModel directly** for the multi-hop demonstration. Graph source instructions and question/GQL examples are supported in preview.
- Adding the **Ontology as context** is a different integration: documented query execution is routed to underlying SQL/KQL/DAX sources. It is not a guarantee of GQL traversal. It is unnecessary as a fourth source for this first demo.
- The graph is the existing ontology's generated graph, not a new standalone graph and not Microsoft Graph/Microsoft 365.
- The previous native ontology natural-language endpoint problem in the 3IQ app is not a test of a future data agent's NL2GQL source. Direct GQL works; actual data-agent NL2GQL must still be rehearsed after manual creation.
- **Do not select the automatically created KQL database named `ConstructionSupplyEventhouse`.** The populated database for this demo is `ConstructionSupplyEvents`.
- Do not add the ontology-generated helper Lakehouse, its SQL endpoint, or the ingestion notebook. They add ambiguity and are not extra business data.
- No Power BI semantic model exists in this workspace; none is assumed or requested.
- The policy KB and simulated Work IQ Search index are Azure resources used by the app, not selected Fabric sources in this preparation. Do not claim the new data agent queried them.

### Selected schema

For the Lakehouse select these 12 `dbo` tables:

`accounts`, `products`, `sales_orders`, `customer_commitments`, `inventory_positions`, `supply_constraints`, `business_risks`, `demand_records`, `activations`, `audience_memberships`, `unified_profiles`, `consent_records`.

Do not select the Lakehouse event mirrors for this initial setup; route timeline questions to KQL. Unselected identity hashes, contact tables and other CDP tables are not needed for the SQL story.

For the KQL database select all four business event tables:

`demand_signals`, `behavioral_events`, `journey_events`, `activation_events`.

Graph source schema selection is not currently supported: the whole graph schema is exposed under the caller's permissions. The graph instructions focus query generation; they are **not** row-level/node-level security controls. Sharing a data agent does not grant access to its sources.

## Paste-ready configuration

### Agent-level instructions

Paste the entire contents of [agent-instructions.md](agent-instructions.md) into **Data agent instructions**.

### Graph source description

```text
Construction relationship network: profiles, audiences, campaigns, demand signals, materials, shared constraints, inventory, commitments, customer accounts and consent. Prefer this source for "follow", "trace", "who else" and multi-hop exposure questions. Uses GQL against the actual ontology-generated GraphModel, not GraphQL or Microsoft 365.
```

Paste [graph-instructions.md](graph-instructions.md) into this source's **Data source instructions**.

### Lakehouse source description

```text
Current synthetic construction business snapshot: orders, commitments, products, inventory pools, proposed allocations, unfilled value, candidate/inbound fields and current activation/consent state. Prefer this source for exact totals, reconciliation and explicit numerical what-if calculations using T-SQL.
```

Paste [lakehouse-instructions.md](lakehouse-instructions.md) into this source's **Data source instructions**.

### KQL source description

```text
Observed synthetic event records: catalogue activity, journey states, activation outcomes and campaign demand signals, with UTC timestamps and stable IDs. Prefer this source for event counts, timelines and observed outcomes in an explicit time window. It does not contain stock balances or detailed consent/supply reason categories.
```

Paste [events-instructions.md](events-instructions.md) into this source's **Data source instructions**.

### Example queries

[query-examples.json](query-examples.json) contains the complete question/query pairs:

- Graph: **G1-G5**.
- Lakehouse: **S1-S4**.
- KQL: **K1-K3**.

Use each example's `question` and `query` in the corresponding source's **Example queries** editor. The JSON is a preparation bundle, **not** a Fabric REST item definition or a promised one-click import format. `expectedRowCount` and `mustExplain` are presenter/rehearsal notes, not instructions to fabricate fixed answers.

The platform selects relevant examples during query generation. Put join syntax, precise column semantics and query constraints at source level; put source routing, answer format and the overall objective at agent level.

## Recommended demo: seven questions, 10-12 minutes

Use English for the prepared prompts and start a fresh test conversation. Announce once that all organizations and data are fictional. Use the exact anchor IDs until the future agent's name resolution has been tested.

### 1. Start with an opportunity, not a risk queue

**Ask (K1 / Events):**

> In the demo observation window from 30 September through 2 October 2026 UTC, what demand signal was recorded for campaign CAMPAIGN-CON-001, the Alder school campaign? Is it confirmed or eligible for allocation?

**Expected:** `DEMAND-CON-001`, `PROD-CON-01`, 300 m2, `confirmed=false`, `allocation_eligible=false`, recorded 2026-10-01 at 11:59 UTC.

**Say:** "This is interest, not an order. We have not created another 300 m2 of committed demand."

### 2. Reveal the shared exposure

**Ask (G1 / Graph):**

> Follow that campaign through its demand signal, material and supply constraint to every exposed commitment, customer and business risk. Who shares the shortage?

Use the explicit `CAMPAIGN-CON-001` form in the example if the conversation loses context.

**Path:** Campaign -> DemandSignal -> Product -> SupplyConstraint -> CustomerCommitment -> BusinessRisk, with CustomerCommitment <- SalesOrder -> Account.

**Expected:**

| Record | Project | Ordered m2 | Proposed m2 | Short m2 | Unfilled EUR |
| --- | --- | ---: | ---: | ---: | ---: |
| `REC-CON-0001` | Alder School Renovation | 800 | 800 | 0 | 0 |
| `REC-CON-0002` | Birch Apartments | 600 | 400 | 200 | 4,000 |
| `REC-CON-0003` | Cedar Office Refurbishment | 400 | 0 | 400 | 8,000 |

**Say:** "The opportunity belongs to one account, but the constraint links us to other customers. This is a dependency, not proof that the campaign caused the shortage."

### 3. Make the totals trustworthy

**Ask (S1 / Lakehouse):**

> Reconcile POOL-CON-01: confirmed order quantities, the current proposal, shared free stock, shortage, total order value and unfilled order value. Count the stock pool only once.

**Expected:** 3 commitments; 1,800 m2 ordered; 1,200 m2 free; 1,200 m2 proposed; 600 m2 short; EUR 36,000 order value; EUR 12,000 unfilled value.

**Say:** "The graph discovers the affected network; SQL reconciles the complete numbers. The 1,200 m2 is one pool, not one balance per customer."

### 4. The graph's nine-hop moment

**Ask (G2 / Graph):**

> Starting from PROFILE-CON-001, traverse audience, activation, campaign, demand signal, product, constraint, commitment and order to find OTHER customer accounts exposed to the same material. Show the intermediate IDs.

**Expected:** two rows, `ACC-CON-002` (Birch) and `ACC-CON-003` (Cedar), with 200 and 400 m2 shortages.

**Show the actual GQL in the run steps.** The nine-edge path is:

`UnifiedProfile -> Audience -> Activation -> Campaign -> DemandSignal -> Product -> SupplyConstraint -> CustomerCommitment <- SalesOrder -> Account`

**Say:** "We started with a customer profile, not an order table or the prejoined queue. The relationships discover the other affected accounts."

This is the technical highlight, not an invitation to use unbounded graph traversal. The query starts from one known profile and follows explicit relationship types.

### 5. Check what actually happened

**Ask (K2 / Events):**

> Show the catalogue activity, journey state and activation outcome for PROFILE-CON-001 in that observation window. Do these events prove conversion or that an email was sent?

**Expected:** three observations:

- 2026-09-30 11:59 UTC: `synthetic_catalogue_view`.
- 2026-10-01 11:59 UTC: `awaiting_supply_review`.
- 2026-10-01 11:59 UTC: `suppressed`.

The latter two share a timestamp. They establish observed states, not a causal sequence, conversion or successful send.

**Say:** "A plausible story is not enough: the event record must support it."

### 6. Break the "stock available means we can contact" assumption

**Ask (G3 / Graph):**

> Trace ACTIVATION-EVENT-CON-010 to its activation, profile, marketing consent, account and commitment REC-CON-0010. Is this a fully covered customer whose marketing consent is denied?

**Expected:** Juniper Learning Builders; 350 m2 ordered and proposed; zero shortage; `PROFILE-CON-010`; `CONSENT-CON-010` denied for email/construction_marketing; logged suppression; current activation status `suppressed_consent`; approval still required.

**Say:** "Supply coverage and permission to market are separate gates. The data agent exposes the facts; it does not authorize outreach."

### 7. Hand off to 3IQ

**Ask (conversation synthesis; no new cross-source join assumed):**

> Using only the verified results above, prepare an evidence brief for the Construction Supply Command Center. Separate the campaign interest from committed demand, identify affected commitments, show the current gap, summarize observed events and consent constraints, and list what is still unknown. Do not approve an allocation, restart a campaign or draft an external promise.

**Expected brief:** the 300 m2 interest remains outside committed demand; records 1/2/3 share the 600 m2 current gap; Birch/Cedar carry the unfilled portion; profile 1 has an observed held/suppressed journey; Juniper is a distinct consent counterexample, not a member of the Alder stock pool. Missing approvals, receipts or qualification decisions are not invented.

**Transition:** "Now the 3IQ app can combine these facts with the written rules and the account-team context to prepare the next human-approved action."

If the future data-agent runtime cannot retain or combine all source results reliably, ask this after showing the three source results explicitly. Do not claim that one federated SQL/KQL/GQL query ran across the three systems.

## High-value extensions

| Extension question | Examples | Verified answer / demo point |
| --- | --- | --- |
| If the 300 m2 interest became an additional confirmed order against unchanged stock, what would the gap become? | S3 | Hypothetical 2,100 m2 requested minus 1,200 free = 900 m2 gap. Today's actual shortage remains 600. No rows or allocations change. |
| How many activation events were suppressed or marked sent in the window? How does that compare with the current consent/supply classification? | K3, then S2 | KQL: 100 suppressed, zero marked sent. SQL: 90 held_supply/granted pairs, 10 suppressed_consent/denied pairs. These are different measures, not an event-time reason field. |
| Elm can review candidate board PROD-CON-06. Which commitments already compete for its own stock? Is it actually spare material? | S4 and G4 | Review is allowed, not approved. Candidate pool has 24 commitments, 6,200 m2 ordered, 4,030 free/proposed and 2,170 short. G4 returns the 24 actual linked commitments/customers; do not sum its repeated 4,030 balance. |
| Starting from the apartment window record, who shares its inbound shipment and which dates can it support? | G5 | One 35-unit inbound on 12 October is split 0/15/20 across records 7/8/9. Harbor's 15 units miss its 10 October commitment; Iris's later 20-unit share can support its 14 October date, conditionally. The school is already covered now. |

The candidate-material extension is the best alternative technical climax when the audience already knows the original school scenario: it expands from three curated records into a genuinely different pool with 24 existing commitments.

## What not to claim

- Do not promise "real-time" streaming: these are seeded snapshots/events. A KQL endpoint does not make the fixture a live operational feed.
- Do not show a campaign actually restarted or a shipment received. Those state transitions and approvals are not in the data.
- Do not call all 24 candidate commitments "24 distinct customers" without a separate distinct-account count.
- Do not infer historical cause solely from current consent/activation status.
- Do not reinterpret `inbound_meets_commitment=false` as a missed delivery when the current order is already fully covered.
- Do not claim policies, legal terms, Teams messages or current stakeholders were retrieved from sources that are not connected.
- Do not present the graph as the only possible way to compute these results. Its advantage here is expressing and explaining relationship paths explicitly.
- Do not claim natural-language data-agent success yet. Only the source-native queries and data facts have been validated.

## Manual setup and rehearsal checklist

When you later choose to create the item yourself:

1. Create it in this workspace/region while the existing F32 is active; confirm the tenant/runtime exposes the GraphModel preview source.
2. Add the three sources above, select the listed SQL/KQL tables, and apply descriptions plus source instructions.
3. Paste the agent-level instructions and add each question/query pair to the correct source. There are 5 graph, 4 SQL and 3 KQL examples, below the documented 100-example-per-source limit.
4. Run K1, G1 and S1 first. Inspect the selected source, generated query and returned IDs/values.
5. Run G2 and verify an actual nine-edge GQL traversal, not a response inferred solely from DemandRecord fields.
6. Test G3, S2 and K3 to ensure consent/current state and logged event outcomes remain distinct.
7. Run the substitution and inbound extensions. Verify unit/currency consistency, deduplicated totals and explicit approval limits.
8. Test a missing ID, an out-of-window request, a source permission failure, and a request to send/approve/change something. Expect explicit uncertainty or read-only refusal, not fabricated success.
9. Inspect all answer tables for truncation. Current documentation caps conversational results at 25 rows/25 columns; source aggregation is needed for complete counts. All prepared example outputs are within that cap.
10. Only then publish/share according to your tenant governance. Users require access to the underlying sources; sharing the agent is not a permission grant.

## Validation evidence and documentation

- [Question/query bundle](query-examples.json): exact source-native queries to seed manually.
- [Live graph results](validation-graph.json): G1-G5, including the nine-hop path and 24 candidate commitments.
- [Live Lakehouse results](validation-lakehouse.json): S1-S4.
- [Live KQL results](validation-events.json): K1-K3.

These results reflect the recorded 2026-10-02 scenario as inspected on 2026-10-03. No source data or Fabric items were changed.

Official guidance checked for this preparation:

- [Supported sources and per-source configuration](https://learn.microsoft.com/fabric/data-science/data-agent-add-datasources) - GraphModel GQL, SQL, KQL, source instructions and examples; up to five sources.
- [Configure your data agent](https://learn.microsoft.com/fabric/data-science/data-agent-configurations) - distinction between agent instructions, source instructions, source descriptions and examples.
- [Ontology as context](https://learn.microsoft.com/fabric/data-science/data-agent-ontology-sources) - underlying SQL/KQL/DAX execution; no assumed cross-source federation.
- [Create a data agent](https://learn.microsoft.com/fabric/data-science/how-to-create-data-agent) - manual configuration and agent-instruction limit.
- [Concepts and limitations](https://learn.microsoft.com/fabric/data-science/concept-data-agent) - read-only behavior, source permissions, 25-row/25-column conversational limits and example limits.
- [GQL graph patterns](https://learn.microsoft.com/fabric/graph/write-graph-pattern-queries) - directed relationships and selective graph patterns.

Source-specific Graph preview guidance is used for the graph setup. Some general documentation lists broader or older source limitations; do not use it to conflate GraphModel with Microsoft 365 Graph or Ontology context.
