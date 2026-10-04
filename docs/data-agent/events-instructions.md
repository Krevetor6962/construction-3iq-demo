# General knowledge

This source is ConstructionSupplyEvents, the populated KQL database inside ConstructionSupplyEventhouse. Use KQL, not SQL or GQL. It contains four synthetic event tables, not an operational streaming connection. Do not use the automatically created database named ConstructionSupplyEventhouse.

# Tables and identifiers

- demand_signals: event_time, demand_signal_id, campaign_id, audience_id, account_id, product_id, product_family_id, opportunity_id, demand_qty, unit, confirmed, allocation_eligible, signal_type, signal_strength.
- behavioral_events: event_time, behavioral_event_id, profile_id, event_type, campaign_id, product_id, content_id, engagement_score.
- journey_events: event_time, journey_event_id, journey_id, journey_step_id, profile_id, event_status, campaign_id.
- activation_events: event_time, activation_event_id, activation_id, profile_id, event_status, suppression_rule_id, destination_id.

IDs are strings and should be preserved exactly. An activation_event_id identifies one logged event; activation_id identifies the activation whose current state is in the Lakehouse/graph. Do not confuse event count, activation count, profile count and customer count.

# Time filters

Filter event_time before joins, unions and aggregation. For the prepared demo, use event_time >= datetime(2026-09-30) and event_time < datetime(2026-10-03). Call this the demo observation window. All event_time values are UTC.

If the user supplies a different period, use it. If they ask for today/last hour, do not substitute the fixture window or invent recent activity. Explain empty results and offer an explicit query over the recorded demo window. Do not use ingestion time as the business-event time.

# What these events establish

- A catalogue view indicates recorded behaviour, not an order.
- A demand signal with confirmed=false and allocation_eligible=false is unconfirmed interest, not allocated demand. Do not add its demand_qty to confirmed orders unless answering a clearly labelled what-if.
- journey_events can show awaiting_supply_review, not that a review was completed.
- activation_events can show suppressed or another recorded status. The table does not contain a detailed reason category or a consent_status column.
- A zero count of event_status='sent' means no such event is recorded in this source/window. It does not prove that an email was never sent in a different system.
- If two events share the same timestamp, display that fact. Sorting them by label is only presentation order and is not proof of causal sequencing.

# Query patterns

Use demand_signals for campaign/time questions, with a campaign_id/product_id filter and explicit unit/confirmed/allocation_eligible output.

For a profile's event trail, union projected rows from behavioral_events, journey_events and activation_events. Preserve event_kind, event_id, profile_id, related_id, observed_status and event_time so different row meanings remain visible. Do not fill a missing campaign_id on activation_events from a guess.

For outcome counts, aggregate in KQL with count/countif. For exact distinct entity counts, select/distinct the intended ID before count rather than relying on an approximate dcount when exactness is required. Do not treat repeated statuses as independent conversion steps.

If asked why an event was suppressed, return its profile_id, activation_id and suppression_rule_id. Use a subsequent graph/SQL query for current consent, activation status and linked commitment context. Those current fields are not automatically a historical cause recorded by the event.

Do not query fictional stock, orders, consent, approval, shipment or policy-document tables here. All four event tables also have Lakehouse/graph mirrors for other purposes; they are duplicate representations, not extra events to add to these counts. Use project/take or source aggregation to keep outputs compact, and explicitly state the window, IDs and any missing evidence.
