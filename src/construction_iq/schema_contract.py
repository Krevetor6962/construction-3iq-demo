from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

ColumnType = Literal["string", "enum", "utc_timestamp", "date", "double", "decimal", "int", "bool"]
FabricTarget = Literal["lakehouse", "eventhouse"]


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    column_type: ColumnType = "string"
    nullable: bool = False
    enum_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableSpec:
    name: str
    target: FabricTarget
    folder: str
    columns: tuple[ColumnSpec, ...]


def C(
    name: str,
    column_type: ColumnType = "string",
    nullable: bool = False,
    enum_values: tuple[str, ...] = (),
) -> ColumnSpec:
    return ColumnSpec(name, column_type, nullable, enum_values)


SCENARIO_RECORD_FIELDS: tuple[tuple[str, ColumnSpec], ...] = (
    ("recordId", C("record_id")),
    ("commitmentId", C("commitment_id")),
    ("businessRiskId", C("business_risk_id")),
    ("accountId", C("account_id")),
    ("accountName", C("account_name")),
    ("projectName", C("project_name")),
    ("productId", C("product_id")),
    ("productName", C("product_name")),
    ("productFamilyId", C("product_family_id")),
    ("unit", C("unit")),
    ("currency", C("currency")),
    ("orderedQty", C("ordered_qty", "int")),
    ("availableQty", C("available_qty", "int")),
    ("allocatedQty", C("allocated_qty", "int")),
    ("shortageQty", C("shortage_qty", "int")),
    ("unitPrice", C("unit_price", "decimal")),
    ("orderValue", C("order_value", "decimal")),
    ("unfilledValue", C("unfilled_value", "decimal")),
    ("priority", C("priority")),
    ("committedDate", C("committed_date", "date")),
    ("constraintId", C("constraint_id")),
    ("clusterId", C("cluster_id")),
    ("approvalRequired", C("approval_required", "bool")),
    ("anchor", C("anchor", "bool")),
    ("sourceType", C("source_type")),
    ("synthetic", C("synthetic", "bool")),
    ("allocationStatus", C("allocation_status", "enum", enum_values=("proposal",))),
    ("allocationRank", C("allocation_rank", "int")),
    ("inventoryPositionId", C("inventory_position_id")),
    ("milestoneName", C("milestone_name")),
    ("milestoneDate", C("milestone_date", "date")),
    ("projectSite", C("project_site")),
    ("substitutionAllowed", C("substitution_allowed", "bool")),
    ("substituteProductId", C("substitute_product_id", nullable=True)),
    ("qualificationStatus", C("qualification_status", "enum", enum_values=("not_requested", "human_review_required"))),
    ("inboundDeliveryId", C("inbound_delivery_id", nullable=True)),
    ("inboundQty", C("inbound_qty", "int")),
    ("inboundDate", C("inbound_date", "date", nullable=True)),
    ("inboundConfirmed", C("inbound_confirmed", "bool")),
    ("plannedInboundQty", C("planned_inbound_qty", "int")),
    ("afterInboundShortageQty", C("after_inbound_shortage_qty", "int")),
    ("inboundMeetsCommitment", C("inbound_meets_commitment", "bool")),
    ("owner", C("owner")),
    ("approvalOwner", C("approval_owner")),
    ("supplyOwner", C("supply_owner")),
    ("qualificationOwner", C("qualification_owner")),
    ("informalPromiseConflict", C("informal_promise_conflict", "bool")),
    ("asOfDate", C("as_of_date", "date")),
    ("demandSignalId", C("demand_signal_id", nullable=True)),
    ("campaignId", C("campaign_id", nullable=True)),
    ("campaignDemandQty", C("campaign_demand_qty", "int", nullable=True)),
    ("campaignConfirmed", C("campaign_confirmed", "bool", nullable=True)),
    ("campaignAllocationEligible", C("campaign_allocation_eligible", "bool", nullable=True)),
    ("profileId", C("profile_id")),
    ("consentId", C("consent_id")),
    ("consentStatus", C("consent_status", "enum", enum_values=("granted", "denied"))),
)

SCENARIO_RECORD_COLUMNS: dict[str, str] = {
    public_name: column.name for public_name, column in SCENARIO_RECORD_FIELDS
}


LAKEHOUSE_TABLES: tuple[TableSpec, ...] = (
    TableSpec("accounts", "lakehouse", "customer", (
        C("account_id"), C("account_name"), C("region"), C("segment_id"),
        C("strategic_tier"), C("priority_score", "double"),
    )),
    TableSpec("customer_contacts", "lakehouse", "customer", (
        C("contact_id"), C("account_id"), C("profile_id", nullable=True),
        C("email_hash"), C("contact_role"), C("is_primary", "bool"),
    )),
    TableSpec("product_families", "lakehouse", "product", (
        C("product_family_id"), C("family_name"), C("technology"), C("lifecycle_state"),
    )),
    TableSpec("products", "lakehouse", "product", (
        C("product_id"), C("product_family_id"), C("product_name"), C("package"),
        C("gross_margin_pct", "double"), C("unit"), C("unit_price", "decimal"), C("currency"),
    )),
    TableSpec("campaigns", "lakehouse", "marketing", (
        C("campaign_id"), C("campaign_name"), C("segment_id"), C("product_family_id"),
        C("start_date", "date"), C("end_date", "date"), C("budget", "decimal"), C("currency"),
    )),
    TableSpec("leads", "lakehouse", "marketing", (
        C("lead_id"), C("campaign_id"), C("account_id"), C("profile_id"), C("product_id"),
        C("opportunity_id", nullable=True), C("lead_score", "double"), C("status"),
    )),
    TableSpec("opportunities", "lakehouse", "sales", (
        C("opportunity_id"), C("account_id"), C("product_id"), C("stage"),
        C("expected_value", "decimal"), C("expected_close_date", "date"), C("currency"),
        C("demand_qty", "int"), C("unit"), C("confirmed", "bool"),
    )),
    TableSpec("sales_orders", "lakehouse", "orders", (
        C("order_id"), C("account_id"), C("product_id"), C("order_qty", "int"),
        C("committed_date", "date"), C("order_value", "decimal"),
        C("unit_price", "decimal"), C("unit"), C("currency"),
    )),
    TableSpec("customer_commitments", "lakehouse", "orders", (
        C("commitment_id"), C("order_id"), C("account_id"), C("product_id"),
        C("contract_id"), C("commit_status"), C("commit_date", "date"), C("priority"),
        C("record_id"), C("cluster_id"), C("project_name"), C("project_site"),
        C("milestone_name"), C("milestone_date", "date"), C("allocation_rank", "int"),
        C("allocated_qty", "int"), C("shortage_qty", "int"), C("planned_inbound_qty", "int"),
        C("substitution_allowed", "bool"), C("substitute_product_id", nullable=True),
        C("qualification_status", "enum", enum_values=("not_requested", "human_review_required")),
        C("approval_required", "bool"), C("anchor", "bool"),
    )),
    TableSpec("inventory_positions", "lakehouse", "supply", (
        C("inventory_position_id"), C("product_id"), C("site"), C("snapshot_date", "date"),
        C("available_qty", "int"), C("reserved_qty", "int"), C("cluster_id"), C("unit"),
        C("inbound_delivery_id", nullable=True), C("inbound_qty", "int"),
        C("inbound_date", "date", nullable=True), C("inbound_confirmed", "bool"),
    )),
    TableSpec("supply_constraints", "lakehouse", "supply", (
        C("constraint_id"), C("product_id", nullable=True), C("product_family_id"),
        C("constraint_type"), C("severity"), C("start_date", "date"), C("end_date", "date"),
        C("cluster_id"), C("description"),
    )),
    TableSpec("business_risks", "lakehouse", "risk", (
        C("business_risk_id"), C("commitment_id"), C("constraint_id"),
        C("risk_score", "double"), C("risk_driver"), C("unfilled_value", "decimal"), C("currency"),
    )),
    TableSpec("unified_profiles", "lakehouse", "cdp", (
        C("profile_id"), C("account_id"), C("contact_id", nullable=True), C("profile_type"),
        C("lifecycle_stage"), C("profile_status"), C("created_at", "utc_timestamp"),
    )),
    TableSpec("identities", "lakehouse", "cdp", (
        C("identity_id"), C("identity_type"), C("identity_value_hash"), C("source_system"),
    )),
    TableSpec("identity_links", "lakehouse", "cdp", (
        C("identity_link_id"), C("identity_id"), C("profile_id"), C("confidence", "double"),
        C("link_method"), C("last_seen_at", "utc_timestamp"),
    )),
    TableSpec("consent_records", "lakehouse", "cdp", (
        C("consent_id"), C("profile_id"), C("channel"), C("purpose"), C("consent_status"),
        C("captured_at", "utc_timestamp"), C("source_system"),
    )),
    TableSpec("profile_traits", "lakehouse", "cdp", (
        C("trait_id"), C("profile_id"), C("trait_name"), C("trait_value"),
        C("confidence", "double"), C("computed_at", "utc_timestamp"),
    )),
    TableSpec("audiences", "lakehouse", "cdp", (
        C("audience_id"), C("audience_name"), C("primary_goal"),
        C("product_family_id", nullable=True), C("channel"),
    )),
    TableSpec("audience_memberships", "lakehouse", "cdp", (
        C("membership_id"), C("audience_id"), C("profile_id"), C("membership_status"),
        C("score", "double"), C("reason"), C("updated_at", "utc_timestamp"),
    )),
    TableSpec("suppression_rules", "lakehouse", "cdp", (
        C("suppression_rule_id"), C("audience_id"), C("channel"),
        C("rule_type"), C("rule_value"), C("severity"),
    )),
    TableSpec("destinations", "lakehouse", "cdp", (
        C("destination_id"), C("destination_name"), C("channel"), C("platform"),
    )),
    TableSpec("activations", "lakehouse", "cdp", (
        C("activation_id"), C("audience_id"), C("campaign_id"), C("destination_id"),
        C("channel"), C("activation_status"), C("launched_at", "utc_timestamp"),
    )),
    TableSpec("offers", "lakehouse", "cdp", (
        C("offer_id"), C("product_id"), C("offer_name"), C("eligibility_rule"), C("priority", "int"),
    )),
    TableSpec("recommendations", "lakehouse", "cdp", (
        C("recommendation_id"), C("profile_id"), C("offer_id"), C("product_id"),
        C("recommendation_reason"), C("confidence", "double"),
    )),
    TableSpec("data_sources", "lakehouse", "governance", (
        C("data_source_id"), C("source_system"), C("source_type"), C("domain"), C("owner"),
    )),
    TableSpec("lineage_records", "lakehouse", "governance", (
        C("lineage_id"), C("data_source_id"), C("target_table"),
        C("refresh_frequency"), C("quality_status"),
    )),
    TableSpec("demand_records", "lakehouse", "risk", tuple(
        column for _, column in SCENARIO_RECORD_FIELDS
    )),
)

EVENTHOUSE_TABLES: tuple[TableSpec, ...] = (
    TableSpec("behavioral_events", "eventhouse", "eventhouse", (
        C("event_time", "utc_timestamp"), C("behavioral_event_id"), C("profile_id"),
        C("event_type"), C("campaign_id", nullable=True), C("product_id", nullable=True),
        C("content_id", nullable=True), C("engagement_score", "double"),
    )),
    TableSpec("journey_events", "eventhouse", "eventhouse", (
        C("event_time", "utc_timestamp"), C("journey_event_id"), C("journey_id"),
        C("journey_step_id"), C("profile_id"), C("event_status"), C("campaign_id"),
    )),
    TableSpec("activation_events", "eventhouse", "eventhouse", (
        C("event_time", "utc_timestamp"), C("activation_event_id"), C("activation_id"),
        C("profile_id"), C("event_status"), C("suppression_rule_id", nullable=True),
        C("destination_id"),
    )),
    TableSpec("demand_signals", "eventhouse", "eventhouse", (
        C("event_time", "utc_timestamp"), C("demand_signal_id"), C("campaign_id"),
        C("audience_id", nullable=True), C("product_family_id"), C("segment_id"),
        C("signal_type"), C("signal_strength", "double"), C("account_id"),
        C("product_id"), C("opportunity_id"), C("demand_qty", "int"), C("unit"),
        C("confirmed", "bool"), C("allocation_eligible", "bool"),
    )),
)

ALL_TABLES: tuple[TableSpec, ...] = LAKEHOUSE_TABLES + EVENTHOUSE_TABLES


def contract_as_dict() -> dict[str, object]:
    return {
        "lakehouse": [asdict(table) for table in LAKEHOUSE_TABLES],
        "eventhouse": [asdict(table) for table in EVENTHOUSE_TABLES],
    }
