---
id: audit
sourceType: synthetic
version: 1
---
# Synthetic evidence and audit policy

## Audit-1: Evidence provenance
Label all fixture rows, policies and collaboration artifacts synthetic. The Work lane is simulated collaboration context, not a live Microsoft 365 connection. Every work document carries a record ID, account ID, owner, approval owner and `sourceType=synthetic`; every benchmark question names its scenario record.

## Audit-2: Trace the reasoning
Cite structured commitment, inventory, constraint and risk IDs for numbers; cite policy ID and section for a rule; cite work-document ID for a fictional note. Preserve source disagreement and missing evidence. A local fixture is not proof that remote retrieval succeeded.

## Audit-3: Snapshot and currency
Use the profile's as-of date and currency. Dates are offsets from that snapshot, not from the presenter's wall clock. Default golden benchmark facts use EUR. Amount columns have currency-neutral names; display their currency explicitly. Currency changes relabel this synthetic price fixture and are not an exchange-rate conversion.

## Audit-4: Approval log
Record the proposed action, impacted commitments, arithmetic, evidence IDs, decision owner and required approval. The proposal remains unapproved until a human decision is recorded outside this demo. Never log real contact data, credentials, or endpoints in fixture evidence.

## Audit-5: Live queue provenance
The Lakehouse `demand_records` table supplies the `DemandRecord` graph entity. Its snake_case properties cover every public scenario-record field, including quantities, monetary values, milestones, owners, qualification and inbound context. The schema's `SCENARIO_RECORD_COLUMNS` maps public camelCase keys to these properties.

In live mode, project these values directly from the graph. Matching a graph ID is not enough: the record must not be enriched from local fixtures. Missing properties or failed retrieval must be reported explicitly. The generated JSON list is an offline fixture and a validation reference, never a hidden live-mode fallback.

The record's `asOfDate` is the snapshot used for date-offset checks. Campaign facts join by both account and product; a missing signal is null, not an invented zero or false. Consent facts follow the account-to-profile-to-consent join.

## Audit-6: Benchmark scope
Run `python scripts\run_benchmark.py --mode offline` for deterministic fixture/workflow validation, or explicitly select `--mode live` for live orchestration. Reports are written to `tests/results/benchmark-offline.json` or `tests/results/benchmark-live.json`.

Fact, governance and provenance checks use the returned context and evidence lanes, not a local manifest or a replacement CSV query. Offline results are not cloud checks. Policy IDs and required terms report evidence availability, not mandatory verbatim model wording. Live generated answers remain review-required; no automatic semantic score or approval is assigned.
