# Companion 1.44.147 — public P99 Wiki mirror

Wiki-backed references now read public HTML pages from `https://p99.funcamp.net`.
The original Wiki's API currently returns a browser challenge; the mirror does
not expose a usable MediaWiki API either. Replacing only the hostname would
therefore leave these features broken. This change parses the rendered article
structures instead. It does not create a new local database or VPS service.

## Behavior

- Market item cards read stats, weapon damage/delay, effects, drop NPCs and
  related quests. NPC/effect detail cards and zone tables use the same source.
- Spells and class skills read descriptions, effects, acquisition tables and
  linked guides. Mobile item/spell detail endpoints use the same mirror.
- Quest summaries and floating checklists preserve nested steps. Catalog
  refresh follows bounded static category pagination, preserving the exact
  encoded filenames used by the archive. Partial refreshes retain the prior
  catalog rather than replacing it with incomplete results.
- All-zone NPC search searches the existing named catalog and loaded zone
  records, then attempts one exact-name mirror page. Its UI explicitly states
  that this is limited coverage, not the original Wiki's global full-text search.
- Public phone reference links, guild loot links and old canonical Wiki links
  resolve to the mirror. Existing saved references and checklist progress remain
  compatible; no bulk article download or new database is introduced.
- Mirror auction values are marked historical and are never averaged with
  current PigParse prices. Coverage and snapshot freshness are not guaranteed.

## Request and content safeguards

Requests retain bounded timeouts and a shared backoff for restrictions.
HTML responses are limited to 2 MB and bounded document depth/node counts.
The article body must exist and contain readable content. Challenges, missing
pages, errors and redirects outside the known source hosts are rejected.
Scripts, event handlers, embeds and foreign resource links are removed before
rendering. No challenge solving or upstream-origin probing is used.

## Validation scope

Authored fixtures cover item/effect/NPC/zone parsing, nested quest steps,
category continuation, spell acquisition, mobile weapon stats, legacy cache
compatibility, source URL handling and HTML trust boundaries. Explicit live
sample reads validated Boneshear (DMG 9 / DLY 20), Chardok, an NPC profile,
Druid Epic Quest, Bravery and Enchanter skills. This is representative coverage,
not a claim that every page in the third-party mirror exists or is current.

Release verification is recorded separately after the complete test suite,
clean portable build, packaged-source comparison and portable self-test.
EverQuest, the installed Companion and the independent VantageUI release are
not replaced or modified by publication.
