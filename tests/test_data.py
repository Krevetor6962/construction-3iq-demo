from __future__ import annotations

import copy
import csv
import json
import re
import tempfile
import unittest
from collections import Counter, defaultdict
from dataclasses import fields, replace
from datetime import date, datetime, timedelta
from pathlib import Path

from construction_iq.config import DATA_ROOT, ROOT, DemoProfile
from construction_iq.generate import (
    PRIORITY_ORDER,
    generate_dataset,
    generate_scenario_records,
    generate_work_documents,
    pool_summaries,
    validate_dataset,
    write_dataset,
)
from construction_iq.schema_contract import (
    ALL_TABLES,
    EVENTHOUSE_TABLES,
    LAKEHOUSE_TABLES,
    SCENARIO_RECORD_COLUMNS,
    ColumnSpec,
    TableSpec,
    contract_as_dict,
)

BASELINE_TABLES = {
    "accounts", "customer_contacts", "product_families", "products", "campaigns",
    "leads", "opportunities", "sales_orders", "customer_commitments", "inventory_positions",
    "supply_constraints", "business_risks", "unified_profiles", "identities",
    "identity_links", "consent_records", "profile_traits", "audiences",
    "audience_memberships", "suppression_rules", "destinations", "activations",
    "offers", "recommendations", "data_sources", "lineage_records",
    "behavioral_events", "journey_events", "activation_events", "demand_signals",
}
EXPECTED_TABLES = BASELINE_TABLES | {"demand_records"}
REQUIRED_RECORD_FIELDS = {
    "recordId", "commitmentId", "businessRiskId", "accountId", "accountName", "projectName",
    "productId", "productName", "productFamilyId", "unit", "currency", "orderedQty",
    "availableQty", "allocatedQty", "shortageQty", "unitPrice", "orderValue", "unfilledValue",
    "priority", "committedDate", "constraintId", "clusterId", "approvalRequired", "anchor",
}
POLICY_IDS = {"allocation", "priority", "campaigns", "substitution", "delivery", "arbitration", "escalation", "audit"}
CDP_RISK_PATH = (
    ("UnifiedProfile", "member_of_audience", "Audience"),
    ("Audience", "activated_through", "Activation"),
    ("Activation", "supports_campaign", "Campaign"),
    ("Campaign", "generates_demand_signal", "DemandSignal"),
    ("DemandSignal", "requests_product", "Product"),
    ("Product", "has_constraint", "SupplyConstraint"),
    ("SupplyConstraint", "exposes_commitment", "CustomerCommitment"),
    ("CustomerCommitment", "has_business_risk", "BusinessRisk"),
)


class ConstructionDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = replace(DemoProfile.load(), seed=42, currency="EUR")
        cls.tables = generate_dataset(cls.profile)
        cls.records = generate_scenario_records(cls.profile)
        cls.by_record = {record["recordId"]: record for record in cls.records}
        cls.pools = pool_summaries(cls.records)
        cls.by_pool = {pool["clusterId"]: pool for pool in cls.pools}
        cls.documents = generate_work_documents(cls.records, cls.profile)

    def test_baseline_schema_and_public_dataclass_fields(self):
        self.assertEqual(len(BASELINE_TABLES), 30)
        self.assertEqual(EXPECTED_TABLES, {table.name for table in ALL_TABLES})
        self.assertEqual(len(LAKEHOUSE_TABLES), 27)
        self.assertEqual(len(EVENTHOUSE_TABLES), 4)
        self.assertEqual([field.name for field in fields(ColumnSpec)], ["name", "column_type", "nullable", "enum_values"])
        self.assertEqual([field.name for field in fields(TableSpec)], ["name", "target", "folder", "columns"])
        self.assertEqual(set(contract_as_dict()), {"lakehouse", "eventhouse"})
        for table in ALL_TABLES:
            self.assertNotIn("_usd", " ".join(column.name for column in table.columns))
            self.assertEqual(table.target, "eventhouse" if table in EVENTHOUSE_TABLES else "lakehouse")

    def test_exact_population_and_unique_keys(self):
        expected = {"accounts": 100, "products": 12, "product_families": 3,
                    "customer_commitments": 200, "sales_orders": 200, "business_risks": 200,
                    "demand_records": 200}
        for name, count in expected.items():
            self.assertEqual(len(self.tables[name]), count, name)
        for table in ALL_TABLES:
            primary = next(column.name for column in table.columns if column.name.endswith("_id"))
            rows = self.tables[table.name]
            self.assertGreater(len(rows), 0, table.name)
            self.assertEqual(len({row[primary] for row in rows}), len(rows), table.name)
        self.assertEqual(sorted(Counter(row["product_family_id"] for row in self.tables["products"]).values()), [4, 4, 4])
        self.assertEqual(set(row["target_table"] for row in self.tables["lineage_records"]), EXPECTED_TABLES)

    def test_schema_types_and_every_foreign_key(self):
        validate_dataset(self.tables)
        broken = copy.deepcopy(self.tables)
        broken["business_risks"][0]["commitment_id"] = "NONEXISTENT"
        with self.assertRaisesRegex(ValueError, "Broken foreign key"):
            validate_dataset(broken)
        broken = copy.deepcopy(self.tables)
        broken["products"][0]["unit_price"] = "twenty"
        with self.assertRaisesRegex(ValueError, "requires a number"):
            validate_dataset(broken)
        broken = copy.deepcopy(self.tables)
        broken["customer_commitments"][0]["qualification_status"] = "approved_equivalent"
        with self.assertRaisesRegex(ValueError, "invalid enum"):
            validate_dataset(broken)

    def test_duplicate_keys_fail_explicitly(self):
        broken = copy.deepcopy(self.tables)
        broken["accounts"].append(copy.deepcopy(broken["accounts"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate accounts"):
            validate_dataset(broken)

    def test_all_records_have_the_same_public_contract(self):
        self.assertEqual(len(self.records), 200)
        self.assertEqual(sum(record["anchor"] for record in self.records), 12)
        self.assertEqual(len({record["recordId"] for record in self.records}), 200)
        self.assertEqual(len({record["commitmentId"] for record in self.records}), 200)
        self.assertEqual(len({record["businessRiskId"] for record in self.records}), 200)
        shape = set(self.records[0])
        for record in self.records:
            self.assertTrue(REQUIRED_RECORD_FIELDS <= set(record))
            self.assertEqual(set(record), shape)
            self.assertIs(type(record["anchor"]), bool)
            self.assertIs(record["approvalRequired"], True)
            self.assertEqual(record["sourceType"], "synthetic")
            self.assertEqual(record["allocationStatus"], "proposal")
            self.assertTrue(record["accountName"].startswith("Synthetic "))
            self.assertTrue(record["projectName"].startswith("Synthetic "))
            self.assertTrue(record["productName"].startswith("Synthetic "))
            date.fromisoformat(record["committedDate"])
            for key in ("orderedQty", "availableQty", "allocatedQty", "shortageQty", "unitPrice", "orderValue", "unfilledValue"):
                self.assertIs(type(record[key]), int)
                self.assertGreaterEqual(record[key], 0)

    def test_records_join_to_all_structured_facts(self):
        commitments = {row["commitment_id"]: row for row in self.tables["customer_commitments"]}
        orders = {row["order_id"]: row for row in self.tables["sales_orders"]}
        products = {row["product_id"]: row for row in self.tables["products"]}
        accounts = {row["account_id"]: row for row in self.tables["accounts"]}
        risks = {row["business_risk_id"]: row for row in self.tables["business_risks"]}
        inventory = {row["inventory_position_id"]: row for row in self.tables["inventory_positions"]}
        constraints = {row["constraint_id"]: row for row in self.tables["supply_constraints"]}
        for record in self.records:
            commitment = commitments[record["commitmentId"]]
            order = orders[commitment["order_id"]]
            product = products[record["productId"]]
            risk = risks[record["businessRiskId"]]
            stock = inventory[record["inventoryPositionId"]]
            constraint = constraints[record["constraintId"]]
            self.assertEqual(record["accountName"], accounts[record["accountId"]]["account_name"])
            self.assertEqual(record["accountId"], order["account_id"])
            self.assertEqual(record["productId"], order["product_id"])
            self.assertEqual(record["productId"], commitment["product_id"])
            self.assertEqual(record["productId"], constraint["product_id"])
            self.assertEqual(record["orderedQty"], order["order_qty"])
            self.assertEqual(record["orderValue"], order["order_value"])
            self.assertEqual(record["unitPrice"], product["unit_price"])
            self.assertEqual(record["unit"], product["unit"])
            self.assertEqual(record["currency"], product["currency"])
            self.assertEqual(record["allocatedQty"], commitment["allocated_qty"])
            self.assertEqual(record["shortageQty"], commitment["shortage_qty"])
            self.assertEqual(record["unfilledValue"], risk["unfilled_value"])
            self.assertEqual(record["commitmentId"], risk["commitment_id"])
            self.assertEqual(record["constraintId"], risk["constraint_id"])
            self.assertEqual(record["clusterId"], stock["cluster_id"])
            self.assertEqual(record["clusterId"], constraint["cluster_id"])
            self.assertEqual(record["availableQty"], stock["available_qty"])
            self.assertEqual(record["committedDate"], order["committed_date"])
            self.assertEqual(record["milestoneDate"], commitment["milestone_date"])
            self.assertEqual(record["orderedQty"] - record["allocatedQty"], record["shortageQty"])
            self.assertEqual(record["orderValue"], record["orderedQty"] * record["unitPrice"])
            self.assertEqual(record["unfilledValue"], record["shortageQty"] * record["unitPrice"])

    def test_demand_record_mapping_covers_every_public_field(self):
        spec = next(table for table in LAKEHOUSE_TABLES if table.name == "demand_records")
        self.assertEqual(spec.folder, "risk")
        self.assertEqual(spec.columns[0].name, "record_id")
        self.assertEqual(set(SCENARIO_RECORD_COLUMNS), set(self.records[0]))
        self.assertEqual(len(SCENARIO_RECORD_COLUMNS), len(set(SCENARIO_RECORD_COLUMNS.values())))
        self.assertEqual(set(SCENARIO_RECORD_COLUMNS.values()), {column.name for column in spec.columns})
        for column in spec.columns:
            self.assertRegex(column.name, r"^[a-z][a-z0-9_]*$")
        for row in self.tables["demand_records"]:
            projected = {public: row[column] for public, column in SCENARIO_RECORD_COLUMNS.items()}
            self.assertEqual(projected, self.by_record[row["record_id"]])

    def test_live_projection_roundtrips_from_only_persisted_table_values(self):
        spec = next(table for table in LAKEHOUSE_TABLES if table.name == "demand_records")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = write_dataset(root, self.profile)
            self.assertEqual(manifest["liveScenarioTable"], "demand_records")
            self.assertEqual(manifest["liveScenarioEntity"], "DemandRecord")
            self.assertEqual(manifest["scenarioRecordColumns"], SCENARIO_RECORD_COLUMNS)
            (root / "scenario-records.json").unlink()
            with (root / "risk" / "demand_records.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            projected_records = []
            for row in rows:
                typed_row = {}
                for column in spec.columns:
                    value = row[column.name]
                    if value == "":
                        self.assertTrue(column.nullable)
                        typed_row[column.name] = None
                    elif column.column_type == "bool":
                        self.assertIn(value, ("true", "false"))
                        typed_row[column.name] = value == "true"
                    elif column.column_type == "int":
                        typed_row[column.name] = int(value)
                    elif column.column_type in ("decimal", "double"):
                        typed_row[column.name] = float(value)
                    else:
                        typed_row[column.name] = value
                projected_records.append({public: typed_row[column] for public, column in SCENARIO_RECORD_COLUMNS.items()})
            self.assertEqual(projected_records, self.records)
            self.assertEqual(len(projected_records), 200)

    def test_exact_golden_arithmetic(self):
        golden = [record for record in self.records if record["clusterId"] == "POOL-CON-01"]
        self.assertEqual([record["orderedQty"] for record in golden], [800, 600, 400])
        self.assertEqual([record["allocatedQty"] for record in golden], [800, 400, 0])
        self.assertEqual([record["shortageQty"] for record in golden], [0, 200, 400])
        self.assertEqual({record["availableQty"] for record in golden}, {1200})
        self.assertEqual({record["unitPrice"] for record in golden}, {20})
        self.assertEqual({record["currency"] for record in golden}, {"EUR"})
        pool = self.by_pool["POOL-CON-01"]
        for key, expected in {"orderedQty": 1800, "availableQty": 1200, "allocatedQty": 1200,
                              "shortageQty": 600, "orderValue": 36000, "unfilledValue": 12000,
                              "customerCount": 3, "impactedCustomerCount": 2}.items():
            self.assertEqual(pool[key], expected)

    def test_shared_pools_and_curated_anchors(self):
        grouped = defaultdict(list)
        anchor_groups = defaultdict(list)
        for record in self.records:
            grouped[record["clusterId"]].append(record)
            if record["anchor"]:
                anchor_groups[record["clusterId"]].append(record)
        self.assertGreaterEqual(len(anchor_groups), 3)
        for members in anchor_groups.values():
            self.assertGreaterEqual(len({record["accountId"] for record in members}), 3)
        for members in grouped.values():
            self.assertGreaterEqual(len({record["accountId"] for record in members}), 3)
            self.assertEqual(len({(record["productId"], record["unit"]) for record in members}), 1)
            free = members[0]["availableQty"]
            total_allocated = sum(record["allocatedQty"] for record in members)
            self.assertEqual(total_allocated, min(free, sum(record["orderedQty"] for record in members)))

    def test_policy_order_drives_each_allocation(self):
        grouped = defaultdict(list)
        for record in self.records:
            grouped[record["clusterId"]].append(record)
        for members in grouped.values():
            ordered = sorted(members, key=lambda record: (
                PRIORITY_ORDER[record["priority"]], record["committedDate"], record["commitmentId"],
            ))
            remaining = members[0]["availableQty"]
            for rank, record in enumerate(ordered, 1):
                self.assertEqual(record["allocationRank"], rank)
                self.assertEqual(record["allocatedQty"], min(remaining, record["orderedQty"]))
                remaining -= record["allocatedQty"]

    def test_duplicate_graph_paths_do_not_duplicate_exposure(self):
        self.assertEqual(pool_summaries(self.records + self.records), self.pools)
        duplicate = copy.deepcopy(self.records[0])
        duplicate["unfilledValue"] += 1
        with self.assertRaisesRegex(ValueError, "Conflicting duplicate"):
            pool_summaries(self.records + [duplicate])

    def test_inconsistent_stock_and_double_allocation_fail(self):
        inconsistent = copy.deepcopy(self.records)
        inconsistent[0]["availableQty"] += 1
        with self.assertRaisesRegex(ValueError, "Inconsistent shared pool"):
            pool_summaries(inconsistent)
        overallocated = copy.deepcopy(self.records)
        overallocated[0]["allocatedQty"] += 1
        with self.assertRaisesRegex(ValueError, "Double allocation"):
            pool_summaries(overallocated)

    def test_inbound_is_separate_conserved_and_date_aware(self):
        windows = [record for record in self.records if record["clusterId"] == "POOL-CON-09"]
        self.assertEqual([record["allocatedQty"] for record in windows], [30, 10, 0])
        self.assertEqual([record["plannedInboundQty"] for record in windows], [0, 15, 20])
        self.assertEqual(sum(record["shortageQty"] for record in windows), 35)
        self.assertEqual(sum(record["plannedInboundQty"] for record in windows), 35)
        self.assertEqual({record["availableQty"] for record in windows}, {40})
        self.assertEqual({record["inboundQty"] for record in windows}, {35})
        self.assertFalse(windows[1]["inboundMeetsCommitment"])
        self.assertTrue(windows[2]["inboundMeetsCommitment"])
        self.assertEqual(windows[1]["inboundDate"], (self.profile.as_of_date + timedelta(days=10)).isoformat())
        for record in self.records:
            self.assertLessEqual(record["plannedInboundQty"], record["shortageQty"])
            self.assertEqual(record["afterInboundShortageQty"], record["shortageQty"] - record["plannedInboundQty"])

    def test_substitution_is_qualification_not_allocation(self):
        allowed = [record for record in self.records if record["substitutionAllowed"]]
        self.assertEqual([record["recordId"] for record in allowed], ["REC-CON-0005", "REC-CON-0006"])
        for record in allowed:
            self.assertEqual(record["substituteProductId"], "PROD-CON-06")
            self.assertEqual(record["qualificationStatus"], "human_review_required")
            self.assertTrue(record["approvalRequired"])
        self.assertEqual(self.by_record["REC-CON-0004"]["substitutionAllowed"], False)
        self.assertEqual(self.by_pool["POOL-CON-05"]["shortageQty"], 450)
        candidate_pool = self.by_pool["POOL-CON-06"]
        self.assertLessEqual(candidate_pool["allocatedQty"], candidate_pool["availableQty"])

    def test_campaign_interest_never_enters_confirmed_allocations(self):
        self.assertEqual(len(self.tables["customer_commitments"]), 200)
        for signal in self.tables["demand_signals"]:
            self.assertIs(signal["confirmed"], False)
            self.assertIs(signal["allocation_eligible"], False)
        for opportunity in self.tables["opportunities"]:
            self.assertIs(opportunity["confirmed"], False)
            self.assertEqual(opportunity["stage"], "unconfirmed_interest")
        school_signal = next(row for row in self.tables["demand_signals"] if row["account_id"] == "ACC-CON-001")
        self.assertEqual(school_signal["demand_qty"], 300)
        self.assertEqual(self.by_pool["POOL-CON-01"]["orderedQty"], 1800)
        self.assertEqual(self.by_pool["POOL-CON-01"]["allocatedQty"], 1200)
        self.assertEqual(self.by_pool["POOL-CON-01"]["unfilledValue"], 12000)

    def test_public_campaign_and_consent_facts_come_from_exact_joins(self):
        signals = {(row["account_id"], row["product_id"]): row for row in self.tables["demand_signals"]}
        profiles = {row["account_id"]: row for row in self.tables["unified_profiles"]}
        consents = {row["profile_id"]: row for row in self.tables["consent_records"]}
        absent = 0
        for record in self.records:
            self.assertEqual(record["asOfDate"], self.profile.as_of_date.isoformat())
            profile = profiles[record["accountId"]]
            consent = consents[profile["profile_id"]]
            self.assertEqual(record["profileId"], profile["profile_id"])
            self.assertEqual(record["consentId"], consent["consent_id"])
            self.assertEqual(record["consentStatus"], consent["consent_status"])
            signal = signals.get((record["accountId"], record["productId"]))
            mapping = {"demandSignalId": "demand_signal_id", "campaignId": "campaign_id",
                       "campaignDemandQty": "demand_qty", "campaignConfirmed": "confirmed",
                       "campaignAllocationEligible": "allocation_eligible"}
            for public, column in mapping.items():
                self.assertEqual(record[public], None if signal is None else signal[column])
            absent += signal is None
        self.assertGreater(absent, 0)
        self.assertEqual(self.by_record["REC-CON-0001"]["campaignDemandQty"], 300)
        self.assertEqual(self.by_record["REC-CON-0010"]["consentStatus"], "denied")

    def test_cdp_demand_chain_and_consent_are_consistent(self):
        profiles = {row["profile_id"]: row for row in self.tables["unified_profiles"]}
        memberships = {row["profile_id"]: row for row in self.tables["audience_memberships"]}
        activations = {row["audience_id"]: row for row in self.tables["activations"]}
        signals = {row["audience_id"]: row for row in self.tables["demand_signals"]}
        opportunities = {row["opportunity_id"]: row for row in self.tables["opportunities"]}
        for consent in self.tables["consent_records"]:
            profile = profiles[consent["profile_id"]]
            membership = memberships[profile["profile_id"]]
            activation = activations[membership["audience_id"]]
            signal = signals[membership["audience_id"]]
            opportunity = opportunities[signal["opportunity_id"]]
            self.assertEqual(signal["account_id"], profile["account_id"])
            self.assertEqual(activation["campaign_id"], signal["campaign_id"])
            self.assertEqual(opportunity["product_id"], signal["product_id"])
            self.assertEqual(opportunity["demand_qty"], signal["demand_qty"])
            if consent["consent_status"] == "denied":
                self.assertEqual(profile["profile_status"], "suppressed")
                self.assertEqual(membership["membership_status"], "suppressed")
                self.assertEqual(activation["activation_status"], "suppressed_consent")
            else:
                self.assertEqual(activation["activation_status"], "held_supply")

    def test_cdp_activation_reaches_supply_and_all_commitment_risks(self):
        ontology = json.loads((ROOT / "ontology" / "construction" / "graph-model" / "construction-ontology.json").read_text(encoding="utf-8"))
        edges = {tuple(edge) for edge in ontology["directedEdges"]}
        self.assertTrue(set(CDP_RISK_PATH) <= edges)
        audiences = {row["audience_id"]: row for row in self.tables["audiences"]}
        campaigns = {row["campaign_id"]: row for row in self.tables["campaigns"]}
        products = {row["product_id"]: row for row in self.tables["products"]}
        commitments = {row["commitment_id"]: row for row in self.tables["customer_commitments"]}
        orders = {row["order_id"]: row for row in self.tables["sales_orders"]}
        reachable_risk_ids = set()
        golden_risks = {}
        for profile in self.tables["unified_profiles"]:
            memberships = [row for row in self.tables["audience_memberships"] if row["profile_id"] == profile["profile_id"]]
            self.assertTrue(memberships, profile["profile_id"])
            for membership in memberships:
                audience = audiences[membership["audience_id"]]
                activations = [row for row in self.tables["activations"] if row["audience_id"] == audience["audience_id"]]
                self.assertTrue(activations, audience["audience_id"])
                for activation in activations:
                    campaign = campaigns[activation["campaign_id"]]
                    signals = [row for row in self.tables["demand_signals"] if row["campaign_id"] == campaign["campaign_id"]]
                    self.assertTrue(signals, campaign["campaign_id"])
                    for signal in signals:
                        self.assertEqual(signal["audience_id"], audience["audience_id"])
                        self.assertEqual(signal["account_id"], profile["account_id"])
                        self.assertFalse(signal["confirmed"])
                        self.assertFalse(signal["allocation_eligible"])
                        product = products[signal["product_id"]]
                        self.assertEqual(product["product_family_id"], campaign["product_family_id"])
                        constraints = [row for row in self.tables["supply_constraints"] if row["product_id"] == product["product_id"]]
                        self.assertTrue(constraints, product["product_id"])
                        for constraint in constraints:
                            risks = [row for row in self.tables["business_risks"] if row["constraint_id"] == constraint["constraint_id"]]
                            self.assertTrue(risks, constraint["constraint_id"])
                            pool_accounts = set()
                            for risk in risks:
                                commitment = commitments[risk["commitment_id"]]
                                order = orders[commitment["order_id"]]
                                self.assertEqual(commitment["product_id"], product["product_id"])
                                self.assertEqual(commitment["cluster_id"], constraint["cluster_id"])
                                self.assertEqual(order["account_id"], commitment["account_id"])
                                self.assertEqual(risk["unfilled_value"], commitment["shortage_qty"] * order["unit_price"])
                                pool_accounts.add(commitment["account_id"])
                                reachable_risk_ids.add(risk["business_risk_id"])
                                if campaign["campaign_id"] == "CAMPAIGN-CON-001":
                                    golden_risks[risk["business_risk_id"]] = risk
                            self.assertGreaterEqual(len(pool_accounts), 3)
        self.assertEqual(reachable_risk_ids, {row["business_risk_id"] for row in self.tables["business_risks"]})
        self.assertEqual(set(golden_risks), {"RISK-CON-0001", "RISK-CON-0002", "RISK-CON-0003"})
        self.assertEqual(sum(row["unfilled_value"] for row in golden_risks.values()), 12000)

    def test_cdp_bridge_relations_are_many_customer_not_family_cartesian_joins(self):
        profiles = {row["profile_id"]: row for row in self.tables["unified_profiles"]}
        audiences = {row["audience_id"]: row for row in self.tables["audiences"]}
        profile_audience_pairs = {
            (row["profile_id"], row["audience_id"]) for row in self.tables["audience_memberships"]
        }
        self.assertEqual(len(profile_audience_pairs), 100)
        for profile_id, audience_id in profile_audience_pairs:
            self.assertIn(profile_id, profiles)
            self.assertIn(audience_id, audiences)
        constraints = {row["constraint_id"]: row for row in self.tables["supply_constraints"]}
        commitments = {row["commitment_id"]: row for row in self.tables["customer_commitments"]}
        constraint_commitment_pairs = {
            (row["constraint_id"], row["commitment_id"]) for row in self.tables["business_risks"]
        }
        self.assertEqual(len(constraint_commitment_pairs), 200)
        for constraint_id, commitment_id in constraint_commitment_pairs:
            self.assertEqual(constraints[constraint_id]["product_id"], commitments[commitment_id]["product_id"])
            self.assertEqual(constraints[constraint_id]["cluster_id"], commitments[commitment_id]["cluster_id"])
        self.assertEqual(
            {commitment_id for constraint_id, commitment_id in constraint_commitment_pairs if constraint_id == "CONSTRAINT-CON-01"},
            {"COMMIT-CON-0001", "COMMIT-CON-0002", "COMMIT-CON-0003"},
        )
        other_insulation_commitments = {
            row["commitment_id"] for row in self.tables["customer_commitments"]
            if row["product_id"] in {"PROD-CON-02", "PROD-CON-03", "PROD-CON-04"}
        }
        self.assertTrue(other_insulation_commitments)
        self.assertTrue(all(("CONSTRAINT-CON-01", commitment_id) not in constraint_commitment_pairs
                            for commitment_id in other_insulation_commitments))

    def test_consent_and_suppression_have_queryable_fixture_relationships(self):
        ontology = json.loads((ROOT / "ontology" / "construction" / "graph-model" / "construction-ontology.json").read_text(encoding="utf-8"))
        edges = {tuple(edge) for edge in ontology["directedEdges"]}
        required = {
            ("UnifiedProfile", "has_consent", "ConsentRecord"),
            ("AudienceMembership", "includes_profile", "UnifiedProfile"),
            ("AudienceMembership", "member_of", "Audience"),
            ("Audience", "governed_by", "SuppressionRule"),
            ("Activation", "activates_audience", "Audience"),
            ("ActivationEvent", "event_for_activation", "Activation"),
            ("ActivationEvent", "event_for_profile", "UnifiedProfile"),
            ("ActivationEvent", "blocked_by", "SuppressionRule"),
        }
        self.assertTrue(required <= edges)
        consent = {row["profile_id"]: row for row in self.tables["consent_records"]}
        profiles = {row["profile_id"]: row for row in self.tables["unified_profiles"]}
        memberships = {row["profile_id"]: row for row in self.tables["audience_memberships"]}
        activations = {row["activation_id"]: row for row in self.tables["activations"]}
        rules = {row["suppression_rule_id"]: row for row in self.tables["suppression_rules"]}
        reasons = Counter()
        for event in self.tables["activation_events"]:
            activation = activations[event["activation_id"]]
            profile = profiles[event["profile_id"]]
            membership = memberships[profile["profile_id"]]
            rule = rules[event["suppression_rule_id"]]
            self.assertEqual(activation["audience_id"], membership["audience_id"])
            self.assertEqual(rule["audience_id"], membership["audience_id"])
            self.assertEqual(rule["channel"], consent[profile["profile_id"]]["channel"])
            self.assertEqual(rule["rule_type"], "supply_and_consent_gate")
            self.assertEqual(rule["severity"], "blocking")
            self.assertEqual(event["destination_id"], activation["destination_id"])
            self.assertEqual(event["event_status"], "suppressed")
            if consent[profile["profile_id"]]["consent_status"] == "denied":
                self.assertEqual(profile["profile_status"], "suppressed")
                self.assertEqual(membership["membership_status"], "suppressed")
                self.assertEqual(activation["activation_status"], "suppressed_consent")
                reasons["consent"] += 1
            else:
                self.assertEqual(profile["profile_status"], "active")
                self.assertEqual(membership["membership_status"], "eligible")
                self.assertEqual(activation["activation_status"], "held_supply")
                reasons["supply"] += 1
        self.assertEqual(reasons, {"consent": 10, "supply": 90})
        protected = self.by_record["REC-CON-0010"]
        self.assertEqual(protected["allocatedQty"], protected["orderedQty"])
        denied_profile = next(row for row in profiles.values() if row["account_id"] == protected["accountId"])
        self.assertEqual(consent[denied_profile["profile_id"]]["consent_status"], "denied")
        denied_audience = memberships[denied_profile["profile_id"]]["audience_id"]
        self.assertTrue(all(row["activation_status"] == "suppressed_consent"
                            for row in activations.values() if row["audience_id"] == denied_audience))

    def test_work_documents_cover_every_record_with_provenance(self):
        self.assertEqual(len(self.documents), 600)
        self.assertEqual(len({document["id"] for document in self.documents}), 600)
        self.assertEqual(Counter(document["recordId"] for document in self.documents),
                         Counter({record["recordId"]: 3 for record in self.records}))
        required = {"id", "recordId", "accountId", "content", "owner", "approvalOwner", "sourceType", "title"}
        for document in self.documents:
            self.assertTrue(required <= set(document))
            record = self.by_record[document["recordId"]]
            self.assertEqual(document["accountId"], record["accountId"])
            self.assertEqual(document["owner"], record["owner"])
            self.assertEqual(document["approvalOwner"], record["approvalOwner"])
            self.assertEqual(document["sourceType"], "synthetic")
            self.assertIn("SYNTHETIC", document["content"])
            self.assertIn("All collaborators and projects are fictional", document["content"])
            self.assertIn("not live Microsoft 365", document["content"])
            self.assertIn(record["commitmentId"], document["content"])
            self.assertIn(record["productId"], document["content"])
        conflict = next(document for document in self.documents if document["id"] == "WORK-REC-CON-0003-message")
        for term in ("full delivery of 400 m2", "CONFLICT", "allocates 0 m2", "unverified", "sales.manager@example.com"):
            self.assertIn(term, conflict["content"])

    def test_contacts_and_fixture_content_are_isolated(self):
        text = json.dumps([self.tables, self.records, self.documents])
        addresses = re.findall(r"[a-zA-Z0-9_.+-]+@(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}", text)
        self.assertGreater(len(addresses), 200)
        self.assertTrue(all(address.endswith("@example.com") for address in addresses))
        self.assertNotRegex(text, r"https?://")
        self.assertNotRegex(text, r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
        self.assertEqual({row["source_type"] for row in self.tables["data_sources"]}, {"synthetic"})

    def test_as_of_date_offsets_apply_to_every_date_column(self):
        shifted = replace(self.profile, as_of_date=self.profile.as_of_date + timedelta(days=91))
        later = generate_dataset(shifted)
        for table in ALL_TABLES:
            for original, updated in zip(self.tables[table.name], later[table.name], strict=True):
                for column in table.columns:
                    before, after = original[column.name], updated[column.name]
                    if before is None:
                        self.assertIsNone(after)
                    elif column.column_type == "date":
                        self.assertEqual(date.fromisoformat(after) - date.fromisoformat(before), timedelta(days=91))
                    elif column.column_type == "utc_timestamp":
                        self.assertEqual(datetime.fromisoformat(after) - datetime.fromisoformat(before), timedelta(days=91))
                    else:
                        self.assertEqual(before, after)
        shifted_records = generate_scenario_records(shifted)
        self.assertEqual(self.records[0]["allocatedQty"], shifted_records[0]["allocatedQty"])
        self.assertEqual(date.fromisoformat(shifted_records[0]["milestoneDate"]) - date.fromisoformat(self.records[0]["milestoneDate"]), timedelta(days=91))

    def test_profile_currency_brand_and_seed_are_respected(self):
        alternate = replace(self.profile, currency="GBP", supplier_name="Synthetic New Supplier", seed=9)
        tables = generate_dataset(alternate)
        records = generate_scenario_records(alternate)
        for table in ALL_TABLES:
            if any(column.name == "currency" for column in table.columns):
                self.assertEqual({row["currency"] for row in tables[table.name]}, {"GBP"})
        self.assertEqual({record["currency"] for record in records}, {"GBP"})
        self.assertEqual([record["allocatedQty"] for record in records[:3]], [800, 400, 0])
        self.assertNotEqual([record["orderedQty"] for record in records[12:]],
                            [record["orderedQty"] for record in self.records[12:]])
        self.assertTrue(all("Synthetic New Supplier" in row["campaign_name"] for row in tables["campaigns"]))
        self.assertTrue(all("Synthetic New Supplier" in document["content"]
                            for document in generate_work_documents(records, alternate)))

    def test_deterministic_csv_json_and_manifest_roundtrip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = write_dataset(root, self.profile)
            first = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            self.assertEqual(write_dataset(root, self.profile), manifest)
            second = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            self.assertEqual(first, second)
            self.assertEqual(len(list(root.rglob("*.csv"))), 31)
            self.assertEqual(json.loads((root / "scenario-records.json").read_text(encoding="utf-8")), self.records)
            self.assertEqual(json.loads((root / "knowledge" / "work-context" / "search-documents.json").read_text(encoding="utf-8")), self.documents)
            self.assertEqual(manifest["counts"], {name: len(rows) for name, rows in self.tables.items()})
            self.assertEqual(manifest["goldenScenario"], self.by_pool["POOL-CON-01"])
            self.assertEqual(manifest["scenarioRecordCount"], 200)
            self.assertEqual(manifest["anchorRecordCount"], 12)
            self.assertEqual(manifest["workContextDocumentCount"], 600)
            for table in ALL_TABLES:
                path = root / table.folder / f"{table.name}.csv"
                with path.open(newline="", encoding="utf-8") as handle:
                    reader = csv.DictReader(handle)
                    self.assertEqual(reader.fieldnames, [column.name for column in table.columns])
                    rows = list(reader)
                self.assertEqual(len(rows), len(self.tables[table.name]))
                for actual, expected in zip(rows, self.tables[table.name], strict=True):
                    for column in table.columns:
                        value = expected[column.name]
                        serialized = "" if value is None else str(value).lower() if isinstance(value, bool) else str(value)
                        self.assertEqual(actual[column.name], serialized)

    def test_persisted_public_shapes_are_lists_and_match_profile(self):
        records = json.loads((DATA_ROOT / "scenario-records.json").read_text(encoding="utf-8"))
        documents = json.loads((ROOT / "knowledge" / "work-context" / "search-documents.json").read_text(encoding="utf-8"))
        manifest = json.loads((DATA_ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertIsInstance(records, list)
        self.assertIsInstance(documents, list)
        self.assertEqual(records, generate_scenario_records(DemoProfile.load()))
        self.assertEqual(len(records), 200)
        self.assertEqual(len(documents), 600)
        self.assertEqual(manifest["counts"]["customer_commitments"], 200)
        self.assertEqual(manifest["counts"]["demand_records"], 200)
        self.assertEqual(manifest["schemaVersion"], 3)
        self.assertEqual(manifest["asOfDate"], DemoProfile.load().as_of_date.isoformat())

    def test_ontology_preserves_node_edge_shape_and_full_cdp_chain(self):
        ontology = json.loads((ROOT / "ontology" / "construction" / "graph-model" / "construction-ontology.json").read_text(encoding="utf-8"))
        self.assertEqual(set(ontology), {"nodeLabels", "directedEdges"})
        labels = {node["label"] for node in ontology["nodeLabels"]}
        ids = {node["idProperty"] for node in ontology["nodeLabels"]}
        self.assertEqual(len(labels), 31)
        self.assertEqual(ids, {next(column.name for column in table.columns if column.name.endswith("_id"))
                               for table in ALL_TABLES})
        edges = {tuple(edge) for edge in ontology["directedEdges"]}
        self.assertEqual(len(edges), len(ontology["directedEdges"]))
        for source, _, target in edges:
            self.assertIn(source, labels)
            self.assertIn(target, labels)
        for edge in (
            ("UnifiedProfile", "member_of_audience", "Audience"),
            ("Audience", "activated_through", "Activation"),
            ("Activation", "supports_campaign", "Campaign"),
            ("Campaign", "generates_demand_signal", "DemandSignal"),
            ("DemandSignal", "requests_product", "Product"),
            ("InventoryPosition", "stocks_product", "Product"),
            ("SupplyConstraint", "exposes_commitment", "CustomerCommitment"),
            ("CustomerCommitment", "has_business_risk", "BusinessRisk"),
            ("DemandRecord", "for_account", "Account"),
            ("DemandRecord", "for_product", "Product"),
            ("DemandRecord", "for_commitment", "CustomerCommitment"),
            ("DemandRecord", "constrained_by", "SupplyConstraint"),
            ("DemandRecord", "has_risk", "BusinessRisk"),
            ("DemandRecord", "from_inventory", "InventoryPosition"),
        ):
            self.assertIn(edge, edges)

    def test_eight_stable_synthetic_policies(self):
        paths = list((ROOT / "knowledge" / "policies").glob("*.md"))
        self.assertEqual({path.stem for path in paths}, POLICY_IDS)
        for path in paths:
            text = path.read_text(encoding="utf-8")
            self.assertIn(f"id: {path.stem}\n", text)
            self.assertIn("sourceType: synthetic", text)
            self.assertIn("## ", text)

    def test_all_benchmark_facts_and_terms_resolve(self):
        cases = json.loads((ROOT / "tests" / "scenarios" / "benchmark.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 20)
        self.assertEqual(len({case["id"] for case in cases}), len(cases))
        intents = POLICY_IDS | {"owners", "draft", "exposure", "provenance", "milestones"}
        for case in cases:
            with self.subTest(question=case["id"]):
                self.assertTrue({"id", "recordId", "question", "expectedIntents"} <= set(case))
                self.assertTrue(case["question"].strip())
                self.assertTrue(case["expectedIntents"])
                self.assertTrue(set(case["expectedIntents"]) <= intents)
                self.assertTrue(case.get("expectedFacts") or case.get("requiredTerms"))
                record = self.by_record[case["recordId"]]
                for key, expected in case.get("expectedFacts", {}).items():
                    if key.startswith("pool."):
                        actual = self.by_pool[record["clusterId"]][key.split(".", 1)[1]]
                    elif key.startswith("campaign."):
                        signal = next(row for row in self.tables["demand_signals"]
                                      if row["account_id"] == record["accountId"] and row["product_id"] == record["productId"])
                        actual = signal[key.split(".", 1)[1]]
                    elif key.startswith("consent."):
                        profile = next(row for row in self.tables["unified_profiles"] if row["account_id"] == record["accountId"])
                        consent = next(row for row in self.tables["consent_records"] if row["profile_id"] == profile["profile_id"])
                        actual = consent[key.split(".", 1)[1]]
                    elif key.endswith("OffsetDays"):
                        actual = (date.fromisoformat(record[key.removesuffix("OffsetDays")]) - self.profile.as_of_date).days
                    else:
                        actual = record[key]
                    self.assertEqual(actual, expected, key)
                self.assertTrue(set(case["policyIds"]) <= POLICY_IDS)
                evidence = "\n".join((ROOT / "knowledge" / "policies" / f"{policy}.md").read_text(encoding="utf-8")
                                     for policy in case["policyIds"]).lower()
                for term in case.get("requiredTerms", []):
                    self.assertIn(term.lower(), evidence)


if __name__ == "__main__":
    unittest.main()
