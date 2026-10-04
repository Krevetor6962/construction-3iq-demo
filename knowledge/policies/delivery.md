---
id: delivery
sourceType: synthetic
version: 1
---
# Synthetic delivery commitment policy

## Delivery-1: Separate on-hand and inbound
Inbound is not on-hand stock. An inbound schedule confirmation is not receipt or logistics clearance. Keep the one delivery quantity separate from the free-stock balance and distribute a later proposed share at most once per commitment. Require receipt and logistics confirmation before promising delivery.

## Delivery-2: Phased window fixture
The window pool has 30 / 25 / 20 units of demand, 40 units free stock, and proposals of 30 / 10 / 0 now. A separate inbound delivery of 35 units is expected at as-of date plus 10 days. Its proposed later shares are 0 / 15 / 20, not 35 for every customer.

The second commitment is due at plus 8 days, so its later 15 units miss the existing date and require explicit customer acceptance of a revised date. The third commitment is due at plus 12 days; its planned 20-unit inbound share precedes that date but still requires receipt, transport confirmation and approval.

## Delivery-3: Messages stay drafts
All customer messages remain draft-only pending supply confirmation and business-owner approval. Never repeat an informal full-delivery promise that conflicts with the available allocation. Missing dates or transport evidence must be disclosed, not replaced with optimistic promises.
