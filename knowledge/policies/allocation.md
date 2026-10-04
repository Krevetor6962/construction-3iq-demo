---
id: allocation
sourceType: synthetic
version: 1
---
# Synthetic allocation policy

## Allocation-1: Count each shared pool once
`availableQty` is free stock already net of other reservations. Do not subtract reserved stock again. The same pool quantity is repeated on customer records for context, not as additional inventory. Group by `clusterId` and deduplicate commitments by `commitmentId`.

## Allocation-2: Conserve stock
Allocate only confirmed commitments, in the order defined in [priority](priority.md). Proposed allocations across a pool must not exceed its one free-stock balance. Shortage is ordered quantity minus proposed allocation; unfilled value is shortage times unit price in the stated currency. Never add window units to square metres.

## Allocation-3: Controlled golden fixture
The insulation pool has 1,200 m2 free stock and three commitments of 800, 600 and 400 m2. Protect the school first, then the apartments, then the office: proposed allocations are 800 / 400 / 0 m2. Demand is 1,800 m2 and shortage is 600 m2. At EUR 20 per m2, order value is EUR 36,000 and unfilled value is EUR 12,000. These are the default EUR-profile benchmark facts, not live stock assertions.

## Allocation-4: Approval boundary
Every allocation is a proposal. The supply planner confirms the stock snapshot; the sales manager approves the allocation; the account owner seeks customer acceptance of changes. The demo does not book stock, change orders, or send communications.
