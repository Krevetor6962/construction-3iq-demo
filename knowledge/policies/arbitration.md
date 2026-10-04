---
id: arbitration
sourceType: synthetic
version: 1
---
# Synthetic cross-customer arbitration policy

## Arbitration-1: Compare the whole pool
Show every confirmed commitment sharing `clusterId`, including fully protected commitments. Report both distinct participating customers and distinct customers with a positive shortage. The golden pool contains three customers, of whom two have positive unfilled quantities.

## Arbitration-2: No duplicate exposure
Deduplicate by commitment ID before summing quantity, order value, or unfilled value across graph paths. A risk node, contact, audience, campaign, or repeated relationship must not duplicate a sales order's exposure. Count the shared available balance once, and never combine different units into an unlabeled total.

## Arbitration-3: Evaluate a change explicitly
Show the before-and-after quantity, deadline impact, and unfilled value for every affected commitment. A manager cannot create more stock by changing priority. Exceptions require the sales manager, supply planner, rationale, affected-customer acknowledgement and an audit record.
