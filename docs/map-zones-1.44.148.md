# Companion 1.44.148 — pointer coordinates, Zones and quest rewards

## Map pointer coordinates

The installed 1.44.147 executable and its bundled map code matched the published
release. Native Windows probes exercised the production frameless Tool window,
the complete Companion application, Mini scaling, synthetic mouse movement and
log-driven zone changes. The coordinate label painted in those cases. The user
then confirmed that **Show pointer coordinates (/loc)** was unchecked in their
running window.

This release enables that option once for existing profiles as requested, and
keeps it enabled for new profiles. A migration marker preserves a later explicit
choice to turn it off. This is a saved-preference correction; the map renderer
and player arrow are unchanged. The pointer location remains independent of the
player's last `/loc`.

## Zones

- Remove an obsolete API parameter that produced invalid mirror article URLs.
- Resolve map names and case-sensitive Wiki titles through one shared mapping,
  including city districts, Nektulos, Chardok and Temple of Veeshan.
- Load the restored zone on first opening without requiring Reload.
- Prevent an old request retry from replacing a newer zone selection.
- Preserve the selected map district when several districts share a Wiki page.
- Use the same title mapping for Market's zone references.

## Quest rewards

Rewards belong to **Quests**, in a dedicated **Rewards** tab. Item names open
item detail cards. Experience, coins and faction remain readable text. The parser
accepts reward sections, infobox rows and inline item cards; lists are no longer
truncated at twelve rewards. Existing quest checklists remain intact.

## Verification scope

Live native application checks loaded Chardok, Temple of Veeshan, Nektulos Forest
and South Qeynos, and displayed all eighteen rewards from Bone Chips (Kaladim).
Automated coverage exercises request URLs, zone selection/retry behavior, reward
parsing and pointer preference migration. These are representative checks; the
third-party mirror remains a historical snapshot with variable page coverage.

The complete suite, portable build, self-test, bundled-source comparisons and
public release verification are recorded in the release verification document.
Publication does not replace the running Companion or modify EverQuest or the
independent VantageUI skin.
