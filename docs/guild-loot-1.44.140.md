# Recent Loot and complete Guild Loot

## Scope

Companion 1.44.140 addresses the character overview's **Recent loot** list,
which is separate from **My DKP History**, and the guild-wide **Loot** tab.
It does not modify OpenDKP guild records or VantageUI.

## Diagnosed failures

- The recent list initially filtered guild loot correctly. When the character
  endpoint finished, it replaced that source with character-scoped records,
  then incorrectly demanded redundant character-name/ID fields. Those records
  can omit owner fields because the URL already identifies their character.
- Character and guild responses use different cost field names, including
  `DkpValue` versus `DKP`.
- The guild client requested only page 1 with 500 items. The generic table
  builder also imposed a separate 2,000-row rendering limit.
- Mobile snapshot/export paths imposed their own 500-loot-row cutoff.

## Intended behavior and safeguards

- Recent Loot stays tied to the selected character, accepts correctly scoped
  ownerless records, rejects explicitly conflicting owners, and keeps item
  actions and selection useful during same-character refreshes.
- Guild Loot loads every public page sequentially, reports progress, validates
  the reported total and replaces the displayed dataset only after completion.
- A failed or superseded request cannot replace a complete history with a
  partial page. Retry is explicit; old-guild results cannot become new-guild loot.
- Repeated legitimate purchases remain distinct. Item-type IDs are not used
  as purchase IDs. Non-advancing/repeated pages and inconsistent totals produce
  an actionable error instead of a false claim of completeness.
- The guild table uses virtual rendering so searching and sorting can cover
  every loaded record without allocating a cell widget for each value.
- Mobile copies remove the arbitrary 500-loot cutoff while retaining their
  existing untrusted-file sanitation and explicit 8 MiB offline-file budget.
  A size-limited offline copy must disclose truncation rather than claim it
  contains the entire history.

## Use

Choose your guild, refresh its public data, then use **Loot** to search all
loaded purchases. Choose your character in **Overview → Recent loot & raids**
for personal purchases. Source availability still depends on OpenDKP and guild
access policies; a public-data error is not an empty history.

Release verification, measured behavior and review limits are recorded in the
matching release evidence document after testing and publication.
