---
id: campaigns
sourceType: synthetic
version: 1
---
# Synthetic campaign demand policy

## Campaigns-1: Interest is not an order
Campaign demand is unconfirmed interest, not an existing commitment. `confirmed=false` and `allocation_eligible=false` keep demand signals outside stock allocation and unfilled-order exposure. A separate campaign opportunity linked to the golden school account is 300 m2; it does not change the pool's 1,800 m2 of confirmed demand or 1,200 m2 of free stock.

## Campaigns-2: Supply and consent gates
Hold constrained-product activations for supply-owner review. Consent is required independently of stock availability. A denied-consent profile remains suppressed even if stock becomes available. Audience membership and a high engagement score are not permission to contact anyone or reserve stock.

## Campaigns-3: Draft-only actions
The marketing owner may draft a pause, audience change, or alternative-interest enquiry. The supply owner and business owner must approve changes. The simulated destination never sends messages and no campaign is activated by the demo.
