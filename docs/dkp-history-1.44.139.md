# My DKP History: item stability

Companion 1.44.139 keeps loot purchases recognizable while OpenDKP's personal
history sources finish loading.

- A known item name is the primary loot title. Raid text, notes, and original
  transaction provenance remain available in the details and search.
- Matching purchase and transaction records are reconciled one-to-one. A partial
  transaction response must not replace the entire character purchase list.
- The selected purchase and its Open item action remain attached to that
  purchase during enrichment, not to its changing display text.
- Distinct purchases of the same item remain distinct. Raid IDs and item-type
  IDs are not purchase identifiers.
- The phone's shared OpenDKP adapter follows the same normalization rules.

Open **Guild DKP & More → My DKP History**, select a character, and choose
**Loot** to inspect purchases. Use **Refresh history** to request fresh sources.
An item link is offered only when its name is supplied or verified by matching
personal purchase evidence; arbitrary transaction text is not treated as an item.

All OpenDKP access remains read-only. This history is not a reconstructed current
balance. Unknown amounts and unidentified pools remain explicitly unknown;
separate DKP pools are never combined.

When a transaction could correspond to more than one purchase, its evidence and
recorded amount remain visible with a possible-duplicate warning. That unresolved
transaction is excluded from known totals instead of guessing or charging twice.

## Verification scope

Regression coverage includes staged response arrivals, partial transactions,
repeated purchases, character/pool boundaries, canonical titles, selection and
item actions, and Python/browser adapter parity. Candidate matching is indexed;
large-history tests verify bounded matching work without truncating records.
Release verification is recorded
separately after the complete suite and portable candidate checks finish.
