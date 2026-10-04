# General knowledge

This source is the real ontology-generated Fabric GraphModel for the construction demo. Query it with GQL. It is not Microsoft Graph/Microsoft 365, GraphQL, Neo4j Cypher or an Eventhouse KQL graph.

Use it to discover and prove relationships. For a request containing "follow", "trace", "who else" or "multi-hop", traverse the requested edges and return intermediate IDs; do not answer solely by filtering the denormalized DemandRecord node. Use the native schema exposed by this source. All business data is synthetic.

# Entity keys and useful properties

- Account: account_id; account_name, region, strategic_tier.
- UnifiedProfile: profile_id; account_id. ConsentRecord: consent_id; profile_id, channel, purpose, consent_status.
- Audience: audience_id. Activation: activation_id; audience_id, campaign_id, activation_status. Campaign: campaign_id.
- DemandSignal: demand_signal_id; campaign_id, account_id, product_id, opportunity_id, demand_qty, unit, confirmed, allocation_eligible, event_time.
- Product: product_id; product_family_id, product_name, unit, unit_price, currency. ProductFamily: product_family_id.
- SupplyConstraint: constraint_id; product_id, product_family_id, cluster_id.
- CustomerCommitment: commitment_id; order_id, account_id, product_id, record_id, cluster_id, project_name, commit_date, milestone_date, allocated_qty, shortage_qty, planned_inbound_qty, priority, allocation_rank, substitution_allowed, substitute_product_id, qualification_status, approval_required.
- SalesOrder: order_id; account_id, product_id, order_qty, committed_date, unit_price, order_value, unit, currency.
- BusinessRisk: business_risk_id; commitment_id, constraint_id, unfilled_value, currency.
- InventoryPosition: inventory_position_id; product_id, cluster_id, available_qty, reserved_qty, snapshot_date, unit, inbound_delivery_id, inbound_qty, inbound_date, inbound_confirmed.
- DemandRecord: record_id; prejoined display fields and arithmetic, commitment_id, account_id, product_id, inventory_position_id, constraint_id, cluster_id, as_of_date, planned_inbound_qty, after_inbound_shortage_qty, inbound_meets_commitment, approval_required. Useful as an anchor and a result projection, not a replacement for traversal.
- ActivationEvent: activation_event_id; event_time, activation_id, profile_id, event_status, suppression_rule_id.
- SuppressionRule: suppression_rule_id; audience_id, channel, rule_type, rule_value.

# Real directed edges

Use these directions exactly; an incoming pattern may traverse a directed edge in reverse:

UnifiedProfile -member_of_audience-> Audience
Audience -activated_through-> Activation
Activation -activates_audience-> Audience
Activation -supports_campaign-> Campaign
Campaign -generates_demand_signal-> DemandSignal
DemandSignal -requests_product-> Product
DemandSignal -indicates_family-> ProductFamily
Product -has_constraint-> SupplyConstraint
SupplyConstraint -exposes_commitment-> CustomerCommitment
CustomerCommitment -has_business_risk-> BusinessRisk
SalesOrder -fulfills_commitment-> CustomerCommitment
SalesOrder -ordered_by-> Account
SalesOrder -orders_product-> Product
UnifiedProfile -associated_with_account-> Account
UnifiedProfile -has_consent-> ConsentRecord
ActivationEvent -event_for_activation-> Activation
ActivationEvent -event_for_profile-> UnifiedProfile
ActivationEvent -blocked_by-> SuppressionRule
Audience -governed_by-> SuppressionRule
InventoryPosition -stocks_product-> Product
DemandRecord -from_inventory-> InventoryPosition
DemandRecord -for_account-> Account
DemandRecord -for_product-> Product
DemandRecord -for_commitment-> CustomerCommitment
DemandRecord -constrained_by-> SupplyConstraint
DemandRecord -has_risk-> BusinessRisk

There is no Project, Shipment, Approval or Substitute entity and no substitutes_for/approved_equivalent edge. Use project fields on commitments, inbound fields on inventory, and explicit candidate product IDs. If matching substitute_product_id to Product.product_id, label this as a property match, not a stored edge.

# Query patterns

- Campaign exposure: Campaign -> DemandSignal -> Product -> SupplyConstraint -> CustomerCommitment -> BusinessRisk; reach the customer through CustomerCommitment <- SalesOrder -> Account.
- Hidden cross-customer path: UnifiedProfile -> Audience -> Activation -> Campaign -> DemandSignal -> Product -> SupplyConstraint -> CustomerCommitment <- SalesOrder -> Account. This is nine edges. Anchor to one profile and exclude Account.account_id equal to the starting profile's account_id when the user asks for OTHER customers.
- Consent versus supply: ActivationEvent -> UnifiedProfile -> ConsentRecord; also follow UnifiedProfile -> Account <- SalesOrder -> CustomerCommitment. Bind the actual event to its activation and actual suppression rule. Filter consent by channel='email' and purpose='construction_marketing' for this demo.
- Shared inventory: selected DemandRecord -> InventoryPosition <- peer DemandRecord. Match the actual inventory node, not just a broad product family.
- Candidate impact: start at the candidate Product, then traverse its own constraint, commitments and customers. Match inventory cluster_id to the commitment cluster_id. Do not move stock from that pool or assume it is uncommitted.

# GQL precision and aggregation

Use backticks for labels, relationship types, properties and potentially reserved aliases. Product and unit are reserved identifiers. Use named, explicit hops with a selective starting ID; avoid unbounded traversal and Cypher-style variable-length syntax. Prefer the supplied tested examples.

Deduplicate by commitment_id before summing exposure. RETURN DISTINCT across event/path IDs can still leave multiple rows for the same commitment; it is not sufficient if those IDs vary. A single profile or campaign may reach many commitments. ProductFamily membership alone does not establish an exact product/pool shortage. When joining BusinessRisk back to the traversed constraint, require matching constraint_id.

Do not sum repeated available_qty or inbound_qty across peer rows. Group stock by inventory_position_id and inbound by inbound_delivery_id. For complete portfolio totals, use the Lakehouse SQL source rather than summing a limited graph result in the answer. Include LIMIT 25 or a smaller requested bound and explain truncation.

Report paths and facts, not causality. Graph event nodes are Lakehouse-backed mirrors; use the KQL source for the authoritative observed timeline. Follow-up questions must retain the starting IDs and must not mistake a previously displayed subset for all matching graph rows.
