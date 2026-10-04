# General knowledge

Use read-only T-SQL against the selected dbo tables in ConstructionSupplyLakehouse. This source is authoritative for exact current-snapshot arithmetic and relational reconciliation. All data is synthetic. The expected demo snapshot is 2026-10-02; inspect snapshot_date/as_of_date rather than using GETDATE() to reinterpret the fixture.

# Tables and grain

- accounts: one row per account_id; readable account_name.
- products: one row per product_id; product_name, product_family_id, unit, unit_price, currency.
- sales_orders: one row per order_id; account_id, product_id, order_qty, committed_date, order_value, unit_price, unit, currency.
- customer_commitments: one row per commitment_id; order_id, record_id, account_id, product_id, cluster_id, project_name, project_site, commit_date, milestone_date, allocated_qty, shortage_qty, allocation_rank, planned_inbound_qty, substitution_allowed, substitute_product_id, qualification_status, approval_required.
- inventory_positions: one row per inventory_position_id; product_id, cluster_id, unit, available_qty, reserved_qty, snapshot_date, inbound_delivery_id, inbound_qty, inbound_date, inbound_confirmed.
- supply_constraints: one row per constraint_id; product_id, product_family_id, cluster_id, severity and active date range.
- business_risks: one row per business_risk_id, linked by commitment_id and constraint_id; unfilled_value, currency. Do not assume there will always be only one risk per commitment.
- demand_records: one row per record_id/commitment, a materialized read model containing display names, as_of_date, unit/currency, pool arithmetic, candidate/inbound fields, profile_id, consent_id, consent_status and campaign fields. Use for ID lookup and convenient snapshot display; use canonical order/commitment/inventory tables to demonstrate reconciliation.
- activations: one row per activation_id, with audience_id, campaign_id, channel, activation_status.
- audience_memberships: membership_id maps audience_id to profile_id. Membership may be many-to-many; do not assume one profile per audience.
- unified_profiles: one row per profile_id; account_id.
- consent_records: consent_id; profile_id, channel, purpose, consent_status and captured_at. Consent is not just an account-wide flag.

# Joins

customer_commitments.order_id = sales_orders.order_id.
sales_orders.account_id = accounts.account_id.
sales_orders.product_id = products.product_id.
customer_commitments.cluster_id = inventory_positions.cluster_id, with matching product_id and unit.
business_risks.commitment_id = customer_commitments.commitment_id and business_risks.constraint_id = supply_constraints.constraint_id.
activations.audience_id = audience_memberships.audience_id.
audience_memberships.profile_id = unified_profiles.profile_id.
consent_records.profile_id = unified_profiles.profile_id; also match channel/purpose to the question.

The sample snapshot has one inventory row per product/pool. If more positions or snapshots exist, group inventory by position and choose the intended snapshot explicitly before joining aggregate commitment totals. Do not duplicate an already aggregated total by joining it to many stock rows.

# When asked about totals

First aggregate at one row per commitment, then per product/pool/unit/currency. Join the shared inventory balance after aggregating orders. Never sum repeated inventory balances, and never use SUM(DISTINCT amount) as a substitute for deduplicating entities: two real commitments can have equal values.

ordered quantity = SUM(sales_orders.order_qty).
proposed quantity = SUM(customer_commitments.allocated_qty).
current shortage = SUM(customer_commitments.shortage_qty).
order value = SUM(sales_orders.order_value).
unfilled order value = SUM(shortage_qty * sales_orders.unit_price), at the commitment grain; reconcile against business_risks only after resolving duplicate risk paths.

An at_risk commitment is still a recorded customer obligation. Do not exclude it from ordered demand merely because its commit_status is not committed.

available_qty is already net of other reservations; do not subtract reserved_qty again. Distinguish that shared free balance from unassigned balance after the current proposal. Proposed allocations are not executed bookings. Do not mix m2 with unit or currencies with each other.

# When asked about activation or consent

For current hold classifications, count distinct activation_id/profile_id pairs after joining audience membership and consent for the intended channel and purpose. For this demo's marketing questions use channel='email' and purpose='construction_marketing'. Report activation_status and consent_status together.

Consent history is not modeled as a full effective-dated history in this snapshot. If multiple conflicting consent records exist, return the ambiguity rather than silently granting permission. Denied consent is not cured by stock availability. Do not infer permission for transactional emails or other purposes from the marketing-consent field.

Current activation statuses are not event timestamps or proof of the historical reason a particular activation event was suppressed. Use the separate KQL source for observed events, carrying exact IDs between the queries.

# When asked about alternatives, inbound or what-if

substitution_allowed and substitute_product_id mean a candidate can be reviewed, not that it is an approved equivalent. Return qualification_status and approval_required. For the candidate product, separately aggregate its own existing orders and proposals and inspect its own inventory pool; never reuse the original material's stock balance.

Count each inbound_delivery_id once. Planned inbound shares are per commitment, and inbound_confirmed does not mean received. Compare inbound_date to each commitment date. Do not infer a late commitment from an inbound flag when the current allocation already covers that commitment.

For an explicitly requested numerical what-if, state the assumptions and keep them separate from current values. Use the supplied extra quantity only for the requested scenario and same unit. A hypothetical additional order does not modify the stored orders, proposals, consent, or supply. Do not label the scenario as a forecast, optimization or approved allocation.

Use TOP and aggregate in SQL for complete counts. Name source, snapshot, IDs, unit/currency and missing evidence in the answer. Do not query standalone Lakehouse Files, execute notebooks, issue DML/DDL, or join this endpoint to the Eventhouse or graph in one fabricated federated query.
