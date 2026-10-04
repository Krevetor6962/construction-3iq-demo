from __future__ import annotations

import csv
import hashlib
import json
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TypeAlias, TypedDict

from construction_iq.config import DATA_ROOT, ROOT, DemoProfile
from construction_iq.schema_contract import ALL_TABLES, SCENARIO_RECORD_COLUMNS

Cell: TypeAlias = str | int | float | bool | None
Row: TypeAlias = dict[str, Cell]
Dataset: TypeAlias = dict[str, list[Row]]
PRIORITY_ORDER = {"contractual": 0, "strategic": 1, "standard": 2}


class BaseScenarioRecord(TypedDict):
    recordId: str
    commitmentId: str
    businessRiskId: str
    accountId: str
    accountName: str
    projectName: str
    productId: str
    productName: str
    productFamilyId: str
    unit: str
    currency: str
    orderedQty: int
    availableQty: int
    allocatedQty: int
    shortageQty: int
    unitPrice: int
    orderValue: int
    unfilledValue: int
    priority: str
    committedDate: str
    constraintId: str
    clusterId: str
    approvalRequired: bool
    anchor: bool
    sourceType: str
    synthetic: bool
    allocationStatus: str
    allocationRank: int
    inventoryPositionId: str
    milestoneName: str
    milestoneDate: str
    projectSite: str
    substitutionAllowed: bool
    substituteProductId: str | None
    qualificationStatus: str
    inboundDeliveryId: str | None
    inboundQty: int
    inboundDate: str | None
    inboundConfirmed: bool
    plannedInboundQty: int
    afterInboundShortageQty: int
    inboundMeetsCommitment: bool
    owner: str
    approvalOwner: str
    supplyOwner: str
    qualificationOwner: str
    informalPromiseConflict: bool
    asOfDate: str


class ScenarioRecord(BaseScenarioRecord):
    demandSignalId: str | None
    campaignId: str | None
    campaignDemandQty: int | None
    campaignConfirmed: bool | None
    campaignAllocationEligible: bool | None
    profileId: str
    consentId: str
    consentStatus: str


class WorkDocument(TypedDict):
    id: str
    recordId: str
    accountId: str
    content: str
    owner: str
    approvalOwner: str
    sourceType: str
    title: str


@dataclass(frozen=True)
class Product:
    number: int
    family: str
    name: str
    unit: str
    price: int
    package: str

    @property
    def id(self) -> str:
        return f"PROD-CON-{self.number:02d}"

    @property
    def family_id(self) -> str:
        return f"FAMILY-{self.family.upper()}"

    @property
    def pool_id(self) -> str:
        return f"POOL-CON-{self.number:02d}"


@dataclass(frozen=True)
class Commitment:
    number: int
    product_number: int
    quantity: int
    due_offset: int
    priority: str
    project_name: str
    milestone: str
    substitute_number: int | None = None

    @property
    def account_number(self) -> int:
        return (self.number - 1) % 100 + 1


def _account_id(number: int) -> str:
    return f"ACC-CON-{number:03d}"


def _account_name(number: int) -> str:
    curated = (
        "Synthetic Alder School Builders", "Synthetic Birch Apartment Contractors",
        "Synthetic Cedar Office Refurbishers", "Synthetic Dune Civic Builders",
        "Synthetic Elm Housing Contractors", "Synthetic Fern Workplace Builders",
        "Synthetic Grove School Contractors", "Synthetic Harbor Residential Builders",
        "Synthetic Iris Office Contractors", "Synthetic Juniper Learning Builders",
        "Synthetic Kite Apartment Contractors", "Synthetic Linden Office Builders",
    )
    return curated[number - 1] if number <= len(curated) else f"Synthetic Construction Partner {number:03d}"


def _catalogue() -> list[Product]:
    return [
        Product(1, "insulation", "Synthetic Wall Insulation A", "m2", 20, "wrapped panels"),
        Product(2, "insulation", "Synthetic Loft Insulation B", "m2", 18, "wrapped rolls"),
        Product(3, "insulation", "Synthetic Floor Insulation C", "m2", 24, "wrapped panels"),
        Product(4, "insulation", "Synthetic Roof Insulation D", "m2", 28, "wrapped panels"),
        Product(5, "plasterboard", "Synthetic Interior Board A", "m2", 12, "pallet"),
        Product(6, "plasterboard", "Synthetic Interior Board B", "m2", 14, "pallet"),
        Product(7, "plasterboard", "Synthetic Ceiling Board C", "m2", 16, "pallet"),
        Product(8, "plasterboard", "Synthetic Partition Board D", "m2", 17, "pallet"),
        Product(9, "windows", "Synthetic Window Assembly A", "unit", 400, "crate"),
        Product(10, "windows", "Synthetic Window Assembly B", "unit", 450, "crate"),
        Product(11, "windows", "Synthetic Window Assembly C", "unit", 500, "crate"),
        Product(12, "windows", "Synthetic Window Assembly D", "unit", 550, "crate"),
    ]


def _commitment_plans(rng: random.Random) -> list[Commitment]:
    plans = [
        Commitment(1, 1, 800, 3, "contractual", "Synthetic Alder School Renovation", "Insulation installation"),
        Commitment(2, 1, 600, 7, "strategic", "Synthetic Birch Apartments", "Internal fit-out"),
        Commitment(3, 1, 400, 14, "standard", "Synthetic Cedar Office Refurbishment", "Office reopening preparation"),
        Commitment(4, 5, 500, 4, "contractual", "Synthetic Dune Community Hall", "Partition installation"),
        Commitment(5, 5, 400, 8, "strategic", "Synthetic Elm Apartments", "Room partitions", 6),
        Commitment(6, 5, 300, 12, "standard", "Synthetic Fern Office Refurbishment", "Interior fit-out", 6),
        Commitment(7, 9, 30, 4, "contractual", "Synthetic Grove School Renovation", "Window installation"),
        Commitment(8, 9, 25, 8, "strategic", "Synthetic Harbor Apartments", "Window installation"),
        Commitment(9, 9, 20, 12, "standard", "Synthetic Iris Office Refurbishment", "Window installation"),
        Commitment(10, 2, 350, 5, "contractual", "Synthetic Juniper School Loft", "Loft installation"),
        Commitment(11, 2, 250, 9, "strategic", "Synthetic Kite Apartments", "Loft installation"),
        Commitment(12, 2, 200, 16, "standard", "Synthetic Linden Office Loft", "Loft installation"),
    ]
    regular_products = (3, 4, 6, 7, 8, 10, 11, 12)
    for number in range(13, 201):
        product_number = regular_products[(number - 13) % len(regular_products)]
        quantity = rng.randrange(10, 51) if product_number >= 9 else rng.randrange(10, 51) * 10
        plans.append(Commitment(
            number, product_number, quantity, rng.randrange(6, 36),
            ("contractual", "strategic", "standard")[rng.randrange(3)],
            f"Synthetic {'School Renovation' if number % 3 == 0 else 'Apartments' if number % 3 == 1 else 'Office Refurbishment'} {number:03d}",
            "Material installation",
        ))
    return plans


def _build_fixtures(profile: DemoProfile) -> tuple[Dataset, list[ScenarioRecord]]:
    rng = random.Random(profile.seed)
    products = _catalogue()
    plans = _commitment_plans(rng)
    tables: Dataset = {table.name: [] for table in ALL_TABLES}
    records: list[BaseScenarioRecord] = []

    def day(offset: int) -> str:
        return (profile.as_of_date + timedelta(days=offset)).isoformat()

    def stamp(offset: int = 0, minutes: int = 0) -> str:
        return (datetime.combine(profile.as_of_date, datetime.min.time(), UTC)
                + timedelta(days=offset, hours=12, minutes=minutes)).isoformat().replace("+00:00", "Z")

    for family in ("insulation", "plasterboard", "windows"):
        tables["product_families"].append({
            "product_family_id": f"FAMILY-{family.upper()}", "family_name": family.title(),
            "technology": "Synthetic catalogue; suitability requires human qualification",
            "lifecycle_state": "active",
        })
    for product in products:
        tables["products"].append({
            "product_id": product.id, "product_family_id": product.family_id,
            "product_name": product.name, "package": product.package,
            "gross_margin_pct": 25.0 + product.number, "unit": product.unit,
            "unit_price": product.price, "currency": profile.currency,
        })
        pool_plans = sorted(
            (plan for plan in plans if plan.product_number == product.number),
            key=lambda plan: (PRIORITY_ORDER[plan.priority], plan.due_offset, plan.number),
        )
        total_demand = sum(plan.quantity for plan in pool_plans)
        free_stock = {1: 1200, 2: 500, 5: 750, 9: 40}.get(product.number, total_demand * 65 // 100)
        inbound_qty = 35 if product.number == 9 else 0
        inbound_date = day(10) if inbound_qty else None
        inbound_id = "INBOUND-CON-09" if inbound_qty else None
        constraint_id = f"CONSTRAINT-CON-{product.number:02d}"
        inventory_id = f"INV-CON-{product.number:02d}"
        tables["inventory_positions"].append({
            "inventory_position_id": inventory_id, "product_id": product.id,
            "site": "Synthetic Central Depot", "snapshot_date": day(0),
            "available_qty": free_stock, "reserved_qty": 40 + product.number * 5,
            "cluster_id": product.pool_id, "unit": product.unit,
            "inbound_delivery_id": inbound_id, "inbound_qty": inbound_qty,
            "inbound_date": inbound_date, "inbound_confirmed": bool(inbound_qty),
        })
        tables["supply_constraints"].append({
            "constraint_id": constraint_id, "product_id": product.id,
            "product_family_id": product.family_id, "constraint_type": "shared_stock",
            "severity": "high", "start_date": day(-1), "end_date": day(45),
            "cluster_id": product.pool_id,
            "description": "Shared free stock is already net of other reservations. Inbound is not on-hand stock.",
        })
        remaining_stock, remaining_inbound = free_stock, inbound_qty
        for rank, plan in enumerate(pool_plans, 1):
            allocated = min(plan.quantity, remaining_stock)
            remaining_stock -= allocated
            shortage = plan.quantity - allocated
            planned_inbound = min(shortage, remaining_inbound)
            remaining_inbound -= planned_inbound
            number = plan.number
            account_id = _account_id(plan.account_number)
            commitment_id = f"COMMIT-CON-{number:04d}"
            order_id = f"ORDER-CON-{number:04d}"
            risk_id = f"RISK-CON-{number:04d}"
            record_id = f"REC-CON-{number:04d}"
            substitute_id = f"PROD-CON-{plan.substitute_number:02d}" if plan.substitute_number else None
            qualification = "human_review_required" if substitute_id else "not_requested"
            project_site = f"Synthetic Project Site {number:04d}"
            tables["sales_orders"].append({
                "order_id": order_id, "account_id": account_id, "product_id": product.id,
                "order_qty": plan.quantity, "committed_date": day(plan.due_offset),
                "order_value": plan.quantity * product.price, "unit_price": product.price,
                "unit": product.unit, "currency": profile.currency,
            })
            tables["customer_commitments"].append({
                "commitment_id": commitment_id, "order_id": order_id, "account_id": account_id,
                "product_id": product.id, "contract_id": f"CONTRACT-CON-{number:04d}",
                "commit_status": "at_risk" if shortage else "committed",
                "commit_date": day(plan.due_offset), "priority": plan.priority,
                "record_id": record_id, "cluster_id": product.pool_id,
                "project_name": plan.project_name, "project_site": project_site,
                "milestone_name": plan.milestone, "milestone_date": day(plan.due_offset + 1),
                "allocation_rank": rank, "allocated_qty": allocated, "shortage_qty": shortage,
                "planned_inbound_qty": planned_inbound, "substitution_allowed": bool(substitute_id),
                "substitute_product_id": substitute_id, "qualification_status": qualification,
                "approval_required": True, "anchor": number <= 12,
            })
            tables["business_risks"].append({
                "business_risk_id": risk_id, "commitment_id": commitment_id,
                "constraint_id": constraint_id, "risk_score": round(shortage / plan.quantity, 4),
                "risk_driver": "unfilled_confirmed_commitment" if shortage else "protected_by_proposed_allocation",
                "unfilled_value": shortage * product.price, "currency": profile.currency,
            })
            records.append({
                "recordId": record_id, "commitmentId": commitment_id, "businessRiskId": risk_id,
                "accountId": account_id, "accountName": _account_name(plan.account_number),
                "projectName": plan.project_name, "productId": product.id,
                "productName": product.name, "productFamilyId": product.family_id,
                "unit": product.unit, "currency": profile.currency, "orderedQty": plan.quantity,
                "availableQty": free_stock, "allocatedQty": allocated, "shortageQty": shortage,
                "unitPrice": product.price, "orderValue": plan.quantity * product.price,
                "unfilledValue": shortage * product.price, "priority": plan.priority,
                "committedDate": day(plan.due_offset), "constraintId": constraint_id,
                "clusterId": product.pool_id, "approvalRequired": True, "anchor": number <= 12,
                "sourceType": "synthetic", "synthetic": True, "allocationStatus": "proposal",
                "allocationRank": rank, "inventoryPositionId": inventory_id,
                "milestoneName": plan.milestone, "milestoneDate": day(plan.due_offset + 1),
                "projectSite": project_site, "substitutionAllowed": bool(substitute_id),
                "substituteProductId": substitute_id, "qualificationStatus": qualification,
                "inboundDeliveryId": inbound_id, "inboundQty": inbound_qty,
                "inboundDate": inbound_date, "inboundConfirmed": bool(inbound_qty),
                "plannedInboundQty": planned_inbound,
                "afterInboundShortageQty": shortage - planned_inbound,
                "inboundMeetsCommitment": bool(planned_inbound and 10 <= plan.due_offset),
                "owner": f"account.owner.{plan.account_number:03d}@example.com",
                "approvalOwner": "sales.manager@example.com",
                "supplyOwner": "supply.planner@example.com",
                "qualificationOwner": "qualification.reviewer@example.com",
                "informalPromiseConflict": number == 3,
                "asOfDate": day(0),
            })

    records.sort(key=lambda record: record["recordId"])
    tables["destinations"].append({
        "destination_id": "DEST-CON-SIMULATED", "destination_name": "Synthetic draft-only email destination",
        "channel": "email", "platform": "synthetic_no_external_delivery",
    })
    for number in range(1, 101):
        account_id = _account_id(number)
        profile_id = f"PROFILE-CON-{number:03d}"
        contact_id = f"CONTACT-CON-{number:03d}"
        identity_id = f"IDENTITY-CON-{number:03d}"
        first_record = records[number - 1]
        product_id = first_record["productId"]
        family_id = first_record["productFamilyId"]
        campaign_id = f"CAMPAIGN-CON-{number:03d}"
        audience_id = f"AUDIENCE-CON-{number:03d}"
        activation_id = f"ACTIVATION-CON-{number:03d}"
        opportunity_id = f"OPPORTUNITY-CON-{number:03d}"
        suppression_id = f"SUPPRESS-CON-{number:03d}"
        offer_id = f"OFFER-CON-{number:03d}"
        segment = ("schools", "housing", "workplaces")[(number - 1) % 3]
        consent_granted = number % 10 != 0
        email_hash = hashlib.sha256(f"synthetic.contact.{number:03d}@example.com".encode()).hexdigest()
        demand_qty = 300 if number == 1 else (5 + number % 10) * (1 if first_record["unit"] == "unit" else 10)
        tables["accounts"].append({
            "account_id": account_id, "account_name": _account_name(number),
            "region": "Synthetic North" if number % 2 else "Synthetic South",
            "segment_id": f"SEG-CON-{segment.upper()}", "strategic_tier": "strategic" if number % 3 == 2 else "standard",
            "priority_score": round(0.4 + (number % 50) / 100, 2),
        })
        tables["customer_contacts"].append({
            "contact_id": contact_id, "account_id": account_id, "profile_id": profile_id,
            "email_hash": email_hash, "contact_role": "synthetic_project_buyer", "is_primary": True,
        })
        tables["unified_profiles"].append({
            "profile_id": profile_id, "account_id": account_id, "contact_id": contact_id,
            "profile_type": "synthetic_b2b_contact", "lifecycle_stage": "construction_planning",
            "profile_status": "active" if consent_granted else "suppressed", "created_at": stamp(-90),
        })
        tables["identities"].append({
            "identity_id": identity_id, "identity_type": "synthetic_email_hash",
            "identity_value_hash": email_hash, "source_system": "synthetic_crm",
        })
        tables["identity_links"].append({
            "identity_link_id": f"LINK-CON-{number:03d}", "identity_id": identity_id,
            "profile_id": profile_id, "confidence": 1.0, "link_method": "synthetic_fixture",
            "last_seen_at": stamp(-1, -number),
        })
        tables["consent_records"].append({
            "consent_id": f"CONSENT-CON-{number:03d}", "profile_id": profile_id,
            "channel": "email", "purpose": "construction_marketing",
            "consent_status": "granted" if consent_granted else "denied",
            "captured_at": stamp(-30), "source_system": "synthetic_consent_register",
        })
        tables["profile_traits"].append({
            "trait_id": f"TRAIT-CON-{number:03d}", "profile_id": profile_id,
            "trait_name": "project_type", "trait_value": segment, "confidence": 1.0,
            "computed_at": stamp(-1),
        })
        tables["audiences"].append({
            "audience_id": audience_id, "audience_name": f"Synthetic {segment} audience {number:03d}",
            "primary_goal": "supply_aware_nurture", "product_family_id": family_id, "channel": "email",
        })
        tables["audience_memberships"].append({
            "membership_id": f"MEMBER-CON-{number:03d}", "audience_id": audience_id,
            "profile_id": profile_id, "membership_status": "eligible" if consent_granted else "suppressed",
            "score": 0.75, "reason": "Synthetic consent and project interest, not confirmed demand",
            "updated_at": stamp(-1),
        })
        tables["suppression_rules"].append({
            "suppression_rule_id": suppression_id, "audience_id": audience_id, "channel": "email",
            "rule_type": "supply_and_consent_gate",
            "rule_value": "Hold constrained-product activation; require consent and supply-owner approval",
            "severity": "blocking",
        })
        tables["campaigns"].append({
            "campaign_id": campaign_id, "campaign_name": f"Synthetic {profile.supplier_name} {segment} nurture {number:03d}",
            "segment_id": f"SEG-CON-{segment.upper()}", "product_family_id": family_id,
            "start_date": day(-7), "end_date": day(30), "budget": 1000 + number * 10,
            "currency": profile.currency,
        })
        tables["activations"].append({
            "activation_id": activation_id, "audience_id": audience_id, "campaign_id": campaign_id,
            "destination_id": "DEST-CON-SIMULATED", "channel": "email",
            "activation_status": "held_supply" if consent_granted else "suppressed_consent",
            "launched_at": stamp(-7),
        })
        tables["opportunities"].append({
            "opportunity_id": opportunity_id, "account_id": account_id, "product_id": product_id,
            "stage": "unconfirmed_interest", "expected_value": demand_qty * first_record["unitPrice"],
            "expected_close_date": day(21), "currency": profile.currency,
            "demand_qty": demand_qty, "unit": first_record["unit"], "confirmed": False,
        })
        tables["leads"].append({
            "lead_id": f"LEAD-CON-{number:03d}", "campaign_id": campaign_id, "account_id": account_id,
            "profile_id": profile_id, "product_id": product_id, "opportunity_id": opportunity_id,
            "lead_score": 0.75, "status": "unconfirmed",
        })
        tables["offers"].append({
            "offer_id": offer_id, "product_id": product_id, "offer_name": f"Synthetic catalogue enquiry {number:03d}",
            "eligibility_rule": "Consent and supply review required; not a stock reservation",
            "priority": 2,
        })
        tables["recommendations"].append({
            "recommendation_id": f"RECOMMEND-CON-{number:03d}", "profile_id": profile_id,
            "offer_id": offer_id, "product_id": product_id,
            "recommendation_reason": "Draft supply-aware nurture; do not promise stock", "confidence": 0.8,
        })
        tables["behavioral_events"].append({
            "event_time": stamp(-2, -number), "behavioral_event_id": f"BEHAVIOR-CON-{number:03d}",
            "profile_id": profile_id, "event_type": "synthetic_catalogue_view",
            "campaign_id": campaign_id, "product_id": product_id,
            "content_id": f"CONTENT-CON-{number:03d}", "engagement_score": 0.75,
        })
        tables["journey_events"].append({
            "event_time": stamp(-1, -number), "journey_event_id": f"JOURNEY-EVENT-CON-{number:03d}",
            "journey_id": f"JOURNEY-CON-{number:03d}", "journey_step_id": "STEP-CON-SUPPLY-REVIEW",
            "profile_id": profile_id, "event_status": "awaiting_supply_review", "campaign_id": campaign_id,
        })
        tables["activation_events"].append({
            "event_time": stamp(-1, -number), "activation_event_id": f"ACTIVATION-EVENT-CON-{number:03d}",
            "activation_id": activation_id, "profile_id": profile_id, "event_status": "suppressed",
            "suppression_rule_id": suppression_id, "destination_id": "DEST-CON-SIMULATED",
        })
        tables["demand_signals"].append({
            "event_time": stamp(-1, -number), "demand_signal_id": f"DEMAND-CON-{number:03d}",
            "campaign_id": campaign_id, "audience_id": audience_id, "product_family_id": family_id,
            "segment_id": f"SEG-CON-{segment.upper()}", "signal_type": "unconfirmed_campaign_interest",
            "signal_strength": 0.75, "account_id": account_id, "product_id": product_id,
            "opportunity_id": opportunity_id, "demand_qty": demand_qty, "unit": first_record["unit"],
            "confirmed": False, "allocation_eligible": False,
        })

    enriched_records = _attach_cdp_facts(records, tables)
    tables["demand_records"] = [_scenario_record_row(record) for record in enriched_records]
    tables["data_sources"].append({
        "data_source_id": "SOURCE-CON-SYNTHETIC", "source_system": "construction_fixture_generator",
        "source_type": "synthetic", "domain": "construction_demand_to_supply",
        "owner": "synthetic.data.steward@example.com",
    })
    for table in ALL_TABLES:
        tables["lineage_records"].append({
            "lineage_id": f"LINEAGE-CON-{table.name}", "data_source_id": "SOURCE-CON-SYNTHETIC",
            "target_table": table.name, "refresh_frequency": "deterministic_manual_generation",
            "quality_status": "synthetic_fixture",
        })
    validate_dataset(tables)
    return tables, enriched_records


def _text_cell(row: Row, key: str) -> str:
    value = row[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"Expected nonempty text in joined field {key}")
    return value


def _attach_cdp_facts(records: list[BaseScenarioRecord], tables: Dataset) -> list[ScenarioRecord]:
    profiles = {row["account_id"]: row for row in tables["unified_profiles"]}
    consents = {row["profile_id"]: row for row in tables["consent_records"]}
    signals = {(row["account_id"], row["product_id"]): row for row in tables["demand_signals"]}
    if len(signals) != len(tables["demand_signals"]):
        raise ValueError("Campaign fixture requires a unique demand signal per account/product")
    if len(profiles) != len(tables["unified_profiles"]) or len(consents) != len(tables["consent_records"]):
        raise ValueError("Consent fixture requires one profile per account and one consent per profile")
    enriched: list[ScenarioRecord] = []
    for record in records:
        profile_id = _text_cell(profiles[record["accountId"]], "profile_id")
        consent = consents[profile_id]
        signal = signals.get((record["accountId"], record["productId"]))
        demand_id: str | None = None
        campaign_id: str | None = None
        demand_qty: int | None = None
        confirmed: bool | None = None
        eligible: bool | None = None
        if signal is not None:
            demand_id = _text_cell(signal, "demand_signal_id")
            campaign_id = _text_cell(signal, "campaign_id")
            quantity = signal["demand_qty"]
            confirmed_value, eligible_value = signal["confirmed"], signal["allocation_eligible"]
            if not isinstance(quantity, int) or isinstance(quantity, bool):
                raise ValueError("Campaign demand_qty must be an integer")
            if not isinstance(confirmed_value, bool) or not isinstance(eligible_value, bool):
                raise ValueError("Campaign eligibility and confirmation must be booleans")
            demand_qty, confirmed, eligible = quantity, confirmed_value, eligible_value
        enriched.append({
            **record, "demandSignalId": demand_id, "campaignId": campaign_id,
            "campaignDemandQty": demand_qty, "campaignConfirmed": confirmed,
            "campaignAllocationEligible": eligible, "profileId": profile_id,
            "consentId": _text_cell(consent, "consent_id"),
            "consentStatus": _text_cell(consent, "consent_status"),
        })
    return enriched


def _scenario_record_row(record: ScenarioRecord) -> Row:
    if set(record) != set(SCENARIO_RECORD_COLUMNS):
        raise ValueError("Scenario record fields do not match the live DemandRecord contract")
    row: Row = {}
    for public_name, column_name in SCENARIO_RECORD_COLUMNS.items():
        value = record.get(public_name)
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise ValueError(f"Unsupported DemandRecord value: {public_name}")
        row[column_name] = value
    return row


def validate_dataset(tables: Dataset) -> None:
    if set(tables) != {table.name for table in ALL_TABLES}:
        raise ValueError(f"Dataset must contain exactly the {len(ALL_TABLES)} schema tables")
    primary_keys: dict[str, str] = {}
    for table in ALL_TABLES:
        primary = next(column.name for column in table.columns if column.name.endswith("_id"))
        primary_keys[primary] = table.name
        seen: set[Cell] = set()
        for row in tables[table.name]:
            if set(row) != {column.name for column in table.columns}:
                raise ValueError(f"Columns do not match the contract for {table.name}")
            key = row[primary]
            if key in seen:
                raise ValueError(f"Duplicate {table.name}.{primary}: {key}")
            seen.add(key)
            for column in table.columns:
                value = row[column.name]
                label = f"{table.name}.{column.name}"
                if value is None:
                    if not column.nullable:
                        raise ValueError(f"{label} cannot be null")
                    continue
                kind = column.column_type
                if kind in ("string", "enum", "date", "utc_timestamp"):
                    if not isinstance(value, str) or not value:
                        raise ValueError(f"{label} requires nonempty text")
                    if kind == "date":
                        date.fromisoformat(value)
                    elif kind == "utc_timestamp":
                        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                        if parsed.utcoffset() != timedelta(0):
                            raise ValueError(f"{label} requires a UTC timestamp")
                    elif kind == "enum" and value not in column.enum_values:
                        raise ValueError(f"{label} has invalid enum value {value}")
                elif kind == "bool" and not isinstance(value, bool):
                    raise ValueError(f"{label} requires a boolean")
                elif kind == "int" and (not isinstance(value, int) or isinstance(value, bool)):
                    raise ValueError(f"{label} requires an integer")
                elif kind in ("double", "decimal") and (
                    not isinstance(value, (int, float)) or isinstance(value, bool)
                ):
                    raise ValueError(f"{label} requires a number")
    key_sets = {key: {row[key] for row in tables[name]} for key, name in primary_keys.items()}
    for table in ALL_TABLES:
        for row in tables[table.name]:
            for column, value in row.items():
                target = "product_id" if column == "substitute_product_id" else column
                if target in key_sets and value is not None and value not in key_sets[target]:
                    raise ValueError(f"Broken foreign key {table.name}.{column}: {value}")


def generate_dataset(profile: DemoProfile | None = None) -> Dataset:
    return _build_fixtures(profile if profile is not None else DemoProfile.load())[0]


def generate_scenario_records(profile: DemoProfile | None = None) -> list[ScenarioRecord]:
    return _build_fixtures(profile if profile is not None else DemoProfile.load())[1]


def generate_work_documents(records: list[ScenarioRecord], profile: DemoProfile) -> list[WorkDocument]:
    documents: list[WorkDocument] = []
    for record in records:
        label = (
            f"SYNTHETIC fixture for {profile.supplier_name}, as of {profile.as_of_date.isoformat()}. "
            "All collaborators and projects are fictional; this is not live Microsoft 365 data. "
            f"Record {record['recordId']}; commitment {record['commitmentId']}; account {record['accountId']}; "
            f"product {record['productId']}; pool {record['clusterId']}. "
        )
        assignment = (
            f"Account owner {record['owner']}; supply owner {record['supplyOwner']}; "
            f"approval owner {record['approvalOwner']}; qualification reviewer {record['qualificationOwner']}. "
            "The supply planner confirms quantities; the sales manager approves changes; "
            "the account owner obtains customer acceptance. External communications are draft-only."
        )
        meeting = (
            f"{record['projectName']} at {record['projectSite']}: milestone {record['milestoneName']} "
            f"on {record['milestoneDate']}; requested delivery {record['committedDate']}. "
            f"Confirmed demand {record['orderedQty']} {record['unit']}; shared free pool "
            f"{record['availableQty']} {record['unit']} already net of other reservations. "
            f"Proposed allocation {record['allocatedQty']}; shortage {record['shortageQty']}; "
            f"unfilled value {record['unfilledValue']} {record['currency']}. "
            "Read allocation ranks with policy priority, milestones and pool-wide impact; no stock is booked."
        )
        if record["substitutionAllowed"]:
            meeting += (
                f" Candidate {record['substituteProductId']} may enter human qualification only. "
                "The permission flag is not technical approval, engineering equivalence, or compliance evidence. "
                "No substitute quantity is allocated. Require documented qualification and customer acceptance."
            )
        if record["inboundQty"]:
            meeting += (
                f" Inbound {record['inboundDeliveryId']} totals {record['inboundQty']} {record['unit']} "
                f"for the entire pool on {record['inboundDate']}; proposed later share "
                f"{record['plannedInboundQty']}. This is not on-hand stock; require receipt and logistics confirmation."
            )
            if record["plannedInboundQty"] and not record["inboundMeetsCommitment"]:
                meeting += " The later share misses the existing delivery date; customer acceptance of a revised date is required."
        message = (
            "Internal synthetic message: check the shared pool once, not once per customer. "
            "Unconfirmed campaign interest is not a commitment and must not consume stock. "
            "All proposed allocations and customer messages require human approval."
        )
        if record["informalPromiseConflict"]:
            message += (
                f" Informal promise by fictional {record['owner']}: full delivery of "
                f"{record['orderedQty']} {record['unit']} by {record['committedDate']}. "
                f"CONFLICT: the approved-policy proposal allocates {record['allocatedQty']} {record['unit']}; "
                "the informal promise is unverified, does not override supply facts, and must be escalated "
                f"to {record['approvalOwner']} before any draft is sent."
            )
        for kind, title, content in (
            ("owners", "Synthetic owner assignment", assignment),
            ("meeting", "Synthetic project coordination meeting", meeting),
            ("message", "Synthetic internal collaboration message", message),
        ):
            documents.append({
                "id": f"WORK-{record['recordId']}-{kind}", "recordId": record["recordId"],
                "accountId": record["accountId"], "content": label + content,
                "owner": record["owner"], "approvalOwner": record["approvalOwner"],
                "sourceType": "synthetic", "title": f"{title}: {record['projectName']}",
            })
    return documents


def pool_summaries(records: list[ScenarioRecord]) -> list[dict[str, object]]:
    unique: dict[str, ScenarioRecord] = {}
    for record in records:
        key = record["commitmentId"]
        if key in unique and unique[key] != record:
            raise ValueError(f"Conflicting duplicate commitment: {key}")
        unique[key] = record
    clusters: dict[str, list[ScenarioRecord]] = {}
    for record in unique.values():
        clusters.setdefault(record["clusterId"], []).append(record)
    summaries: list[dict[str, object]] = []
    for cluster_id, members in sorted(clusters.items()):
        first = members[0]
        pool_facts = {
            (record["availableQty"], record["inboundQty"], record["inboundDate"],
             record["unit"], record["currency"], record["productId"])
            for record in members
        }
        if len(pool_facts) != 1:
            raise ValueError(f"Inconsistent shared pool facts: {cluster_id}")
        allocated = sum(record["allocatedQty"] for record in members)
        inbound_allocated = sum(record["plannedInboundQty"] for record in members)
        if allocated > first["availableQty"] or inbound_allocated > first["inboundQty"]:
            raise ValueError(f"Double allocation in pool: {cluster_id}")
        summaries.append({
            "clusterId": cluster_id, "productId": first["productId"], "unit": first["unit"],
            "currency": first["currency"], "availableQty": first["availableQty"],
            "orderedQty": sum(record["orderedQty"] for record in members),
            "allocatedQty": allocated, "shortageQty": sum(record["shortageQty"] for record in members),
            "orderValue": sum(record["orderValue"] for record in members),
            "unfilledValue": sum(record["unfilledValue"] for record in members),
            "inboundQty": first["inboundQty"], "plannedInboundQty": inbound_allocated,
            "inboundDate": first["inboundDate"], "customerCount": len({record["accountId"] for record in members}),
            "impactedCustomerCount": len({record["accountId"] for record in members if record["shortageQty"]}),
            "commitmentIds": [record["commitmentId"] for record in members],
        })
    return summaries


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def write_dataset(output_root: Path = DATA_ROOT, profile: DemoProfile | None = None) -> dict[str, object]:
    """Write the fixture and manifest; custom output roots contain their own knowledge folder."""
    selected = profile if profile is not None else DemoProfile.load()
    tables, records = _build_fixtures(selected)
    summaries = pool_summaries(records)
    documents = generate_work_documents(records, selected)
    output_root = output_root.resolve()
    context_path = (
        ROOT / "knowledge" / "work-context" / "search-documents.json"
        if output_root == DATA_ROOT.resolve()
        else output_root / "knowledge" / "work-context" / "search-documents.json"
    )
    counts = {table.name: len(tables[table.name]) for table in ALL_TABLES}
    table_manifest: list[dict[str, object]] = []
    for table in ALL_TABLES:
        relative = Path(table.folder) / f"{table.name}.csv"
        path = output_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=[column.name for column in table.columns], lineterminator="\n")
            writer.writeheader()
            for row in tables[table.name]:
                writer.writerow({
                    key: str(value).lower() if isinstance(value, bool) else value
                    for key, value in row.items()
                })
        table_manifest.append({
            "name": table.name, "target": table.target, "folder": table.folder,
            "path": relative.as_posix(), "rowCount": counts[table.name],
        })
    _write_json(output_root / "scenario-records.json", records)
    _write_json(context_path, documents)
    manifest: dict[str, object] = {
        "schemaVersion": 3, "sourceType": "synthetic", "synthetic": True,
        "supplierName": selected.supplier_name, "asOfDate": selected.as_of_date.isoformat(),
        "seed": selected.seed, "currency": selected.currency, "counts": counts, "tables": table_manifest,
        "scenarioRecordCount": len(records), "anchorRecordCount": sum(record["anchor"] for record in records),
        "scenarioRecordsPath": "scenario-records.json", "workContextDocumentCount": len(documents),
        "liveScenarioTable": "demand_records", "liveScenarioEntity": "DemandRecord",
        "scenarioRecordColumns": SCENARIO_RECORD_COLUMNS,
        "workContextPath": "../../knowledge/work-context/search-documents.json"
        if output_root == DATA_ROOT.resolve() else "knowledge/work-context/search-documents.json",
        "goldenScenario": next(pool for pool in summaries if pool["clusterId"] == "POOL-CON-01"),
        "pools": summaries,
        "semantics": {
            "availableQty": "Shared pool free stock, already net of other reservations; count once per clusterId.",
            "allocatedQty": "Proposed per-commitment on-hand allocation; not an approved stock booking.",
            "shortageQty": "orderedQty minus allocatedQty; inbound is not on-hand.",
            "unfilledValue": "shortageQty times unitPrice; deduplicate by commitmentId before aggregation.",
            "plannedInboundQty": "Separate pool-conserving later proposal; receipt, logistics and approval still required.",
            "substitutionAllowed": "Permission to request human qualification, never engineering approval or allocation.",
            "campaignDemand": "Unconfirmed opportunities and demand signals are excluded from commitments and allocation.",
            "quantities": "Aggregate only within a product/unit pool; do not add window units to square metres.",
            "liveScenarioRecords": "Project DemandRecord properties using scenarioRecordColumns; never enrich live graph results from local fixtures.",
            "campaignFields": "Join demand signals by account_id AND product_id; null means no matching campaign signal, not zero demand or denied eligibility.",
            "consentFields": "Join account to unified profile to its consent record. asOfDate carries the fixture snapshot for date-offset checks.",
        },
    }
    _write_json(output_root / "manifest.json", manifest)
    return manifest
