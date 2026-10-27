"""Read domain details from public P99 mirror pages, without fabricating Wiki markup."""

from __future__ import annotations

import re
from urllib.parse import unquote, urljoin, urlsplit

from vantage.helpers.wiki_source import page_url, parse_html, section_html


def walk(node):
    yield node
    for child in node.children:
        if not isinstance(child, str):
            yield from walk(child)


def has_class(node, name):
    return name in node.attrs.get("class", "").split()


def clean_tree(rendered):
    """Remove navigation and hidden item tooltips before reading visible content."""
    root = parse_html(str(rendered or ""))
    root = next((node for node in walk(root)
                 if node.attrs.get("id") == "mw-content-text"), root)

    def prune(node):
        keep = []
        for child in node.children:
            if isinstance(child, str):
                keep.append(child)
                continue
            classes = set(child.attrs.get("class", "").split())
            if (child.tag in {"script", "style", "nav", "form"} or
                    classes & {"hb", "toc", "mw-editsection", "noprint", "navbox"} or
                    child.attrs.get("id") in {"toc", "catlinks", "mw-navigation"} or
                    re.search(r"display\s*:\s*none", child.attrs.get("style", ""), re.I)):
                continue
            prune(child)
            keep.append(child)
        node.children[:] = keep

    prune(root)
    return root


def visible_text(node, *, lines=False, skip_lists=False):
    chunks = []

    def visit(value):
        if isinstance(value, str):
            chunks.append(value)
            return
        if skip_lists and value is not node and value.tag in {"ul", "ol", "dl"}:
            return
        block = value.tag in {"br", "p", "div", "li", "tr", "h2", "h3", "h4", "h5", "h6"}
        if block:
            chunks.append("\n")
        for child in value.children:
            visit(child)
        if block:
            chunks.append("\n")

    visit(node)
    text = "".join(chunks).replace("\xa0", " ")
    if lines:
        return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())
    return " ".join(text.split())


def page_links(node):
    entries = []
    seen = set()
    for link in walk(node):
        if link.tag != "a":
            continue
        href = link.attrs.get("href", "")
        parsed = urlsplit(urljoin("https://p99.funcamp.net/", href))
        if (not href or href.startswith("#") or parsed.hostname not in {
                "p99.funcamp.net", "wiki.project1999.com"}):
            continue
        target = unquote(parsed.path.lstrip("/")).replace("_", " ")
        if not target or re.match(r"(?:Category|File|Image|Special|Talk|User|Template|Help):", target, re.I) or target.startswith("index.php"):
            continue
        name = visible_text(link)
        if not name or target.casefold() in seen:
            continue
        seen.add(target.casefold())
        entries.append({"name": name, "target": target, "url": page_url(target)})
    return entries


def table_fields(root):
    """Read ordinary label/value rows and single-cell NPC label rows."""
    result = {}
    for row in walk(root):
        if row.tag != "tr":
            continue
        cells = [child for child in row.children if not isinstance(child, str)
                 and child.tag in {"th", "td"}]
        if len(cells) >= 2 and len(cells) % 2 == 0:
            for index in range(0, len(cells), 2):
                label = visible_text(cells[index]).rstrip(":").strip()
                result.setdefault(label.casefold(), cells[index + 1])
        elif len(cells) == 1:
            bold = next((node for node in walk(cells[0]) if node.tag in {"b", "strong"}), None)
            if bold is not None:
                label = visible_text(bold).rstrip(":").strip()
                if label:
                    result.setdefault(label.casefold(), cells[0])
    return result


def field_text(fields, label):
    node = fields.get(label.casefold())
    if node is None:
        return ""
    return re.sub(r"^" + re.escape(label) + r"\s*:\s*", "",
                  visible_text(node), flags=re.I).strip()


def _section(root, names):
    return clean_tree(section_html(root.html(), names))


def parse_item_html(rendered_html, fallback_name=""):
    root = clean_tree(rendered_html)
    box = next((node for node in walk(root) if has_class(node, "itemdata")), None)
    if box is None:
        raise ValueError("The mirror page does not contain an item stat block")
    name_node = next((node for node in walk(root) if has_class(node, "itemtitle")), None)
    stats = visible_text(box, lines=True)
    numeric = {}
    for key, label in (("dmg", "DMG|Damage"), ("dly", "DLY|Delay"),
                       ("ac", "AC"), ("hp", "HP"), ("mana", "Mana")):
        match = re.search(r"\b(?:" + label + r")\s*:\s*([+-]?\d+)\b", stats, re.I)
        if match:
            numeric[key] = int(match.group(1))
    effects = []
    for line in re.split(r"<br\s*/?>", box.html(), flags=re.I):
        line_node = clean_tree(line)
        if re.search(r"\b(?:Effect|Focus Effect|Worn Effect|Proc)\s*:", visible_text(line_node), re.I):
            effects.extend(page_links(line_node)[:1])
    drops_root = _section(root, ("Drops From",))
    drops = []
    zone = {}
    # The item template groups each list of NPCs under a linked zone paragraph.
    for node in walk(drops_root):
        if node.tag == "p":
            links = page_links(node)
            if links:
                zone = links[0]
        elif node.tag == "li":
            links = page_links(node)
            if links:
                npc = links[0]
                drops.append({"npc": npc["name"], "npc_target": npc["target"],
                              "npc_url": npc["url"], "zone": zone.get("name", "Zone not listed"),
                              "zone_target": zone.get("target", ""), "zone_url": zone.get("url", "")})
    image = next((node.attrs.get("src", "") for node in walk(box)
                  if node.tag == "img" and re.search(r"Item[_ ]\d+", node.attrs.get("src", ""))), "")
    return {"name": visible_text(name_node) if name_node is not None else fallback_name,
            "stats": stats, "numeric_stats": numeric, "effects": effects,
            "image": unquote(urlsplit(image).path.rsplit("/", 1)[-1]),
            "drops": drops, "related_quests": page_links(_section(root, ("Related Quests",))),
            "notes": visible_text(_section(root, ("Notes",)))[:600],
            "source": "P99 Wiki mirror"}


def parse_entity_html(rendered_html, fallback_name="", kind="npc"):
    root = clean_tree(rendered_html)
    if kind == "npc":
        box = next((node for node in walk(root) if has_class(node, "mobStatsBox")), None)
        if box is None:
            raise ValueError("The mirror page does not contain an NPC profile")
        fields = table_fields(box)
        facts = [(label, field_text(fields, label)) for label in (
            "Race", "Class", "Level", "Zone", "Location", "HP", "Damage per hit")
                 if field_text(fields, label)]
        title = next((node for node in walk(box) if node.tag == "th"), None)
        drops = [link["name"] for link in page_links(_section(root, ("Known Loot",)))]
        summary = visible_text(_section(root, ("Description",)))
        if drops:
            facts.append(("Known loot", f"{len(drops)} listed items"))
            summary = (summary + "\n\nKNOWN LOOT\n" + "\n".join("• " + item for item in drops)).strip()
        return {"name": visible_text(title) if title is not None else fallback_name,
                "kind": "NPC", "facts": facts, "drops": drops,
                "related_quests": page_links(_section(root, ("Related Quests",))),
                "summary": summary, "source": "P99 Wiki mirror"}
    if kind == "zone":
        zone = parse_zone_html(rendered_html, fallback_name)
        return {"name": zone["name"], "kind": "ZONE", "summary": zone["summary"],
                "facts": [("Enemy levels", zone["levels"])] if zone["levels"] else []}
    fields = table_fields(root)
    facts = [(label, field_text(fields, label)) for label in (
        "Spell Type", "Target", "Target Type", "Duration", "Resist", "Casting Time", "Recast Time", "Range", "Mana", "Skill")
             if field_text(fields, label)]
    effects = [field_text(fields, label) for label in fields if re.fullmatch(r"\d+", label)]
    description = visible_text(_section(root, ("Description", "Effects", "Spell Effects")))
    if effects:
        description = (description + "\n\nWHAT IT DOES\n" + "\n".join(effects)).strip()
    return {"name": fallback_name.replace("_", " "), "kind": "EFFECT", "facts": facts,
            "summary": description or
                       visible_text(root)[:2500], "source": "P99 Wiki mirror"}


def parse_zone_html(rendered_html, fallback_name=""):
    root = clean_tree(rendered_html)
    fields = table_fields(root)
    notable = [entry["name"] for entry in page_links(fields["notable npcs"])] if "notable npcs" in fields else []
    unique = [entry["name"] for entry in page_links(fields["unique items"])] if "unique items" in fields else []
    named_keys = {name.casefold() for name in notable}
    mobs = []
    for table in walk(root):
        if table.tag != "table":
            continue
        headers = [visible_text(node).casefold() for node in walk(table) if node.tag == "th"]
        if "npc name" not in headers or "level" not in headers:
            continue
        for row in walk(table):
            if row.tag != "tr":
                continue
            cells = [node for node in row.children if not isinstance(node, str) and node.tag == "td"]
            if len(cells) < 6:
                continue
            links = page_links(cells[0])
            name = links[0]["name"] if links else visible_text(cells[0])
            drops = [entry["name"] for entry in page_links(cells[5])]
            mobs.append({"name": name, "target": links[0]["target"] if links else name,
                         "named": name.casefold() in named_keys,
                         "race": visible_text(cells[1]), "class": visible_text(cells[2]),
                         "level": visible_text(cells[3]), "location": visible_text(cells[4]),
                         "drops": drops, "loot": ", ".join(drops) or visible_text(cells[5]),
                         "description": visible_text(cells[6]) if len(cells) > 6 else ""})
        break
    # The introduction is outside tables, avoiding nested item stats in the summary.
    lead = []
    def introduction(node):
        for child in node.children:
            if isinstance(child, str):
                continue
            if child.tag in {"h2", "h3"}:
                return True
            if child.tag == "p" and visible_text(child):
                lead.append(visible_text(child))
            elif child.tag not in {"table", "p"} and not has_class(child, "thumb"):
                if introduction(child):
                    return True
        return False
    introduction(root)
    era = next((visible_text(node) for node in walk(root) if has_class(node, "era")), "")
    return {"name": fallback_name.replace("_", " "), "summary": "\n\n".join(lead)[:1600],
            "era": era, "levels": field_text(fields, "Level of Monsters"),
            "types": field_text(fields, "Types of Monsters"), "notable": notable,
            "unique_items": unique, "map_image": "", "mobs": mobs,
            "source": "P99 Wiki mirror"}

