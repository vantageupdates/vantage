"""GamParse-parity clipboard and file formats for Vantage combat data."""

from __future__ import annotations

from html import escape
import xml.etree.ElementTree as ET


def compact_number(value):
    value = float(value or 0)
    for threshold, suffix in ((1_000_000_000, "b"), (1_000_000, "m"),
                              (1_000, "k")):
        if abs(value) >= threshold:
            scaled = value / threshold
            precision = 0 if scaled >= 100 else 1
            rendered = f"{scaled:.{precision}f}"
            if "." in rendered:
                rendered = rendered.rstrip("0").rstrip(".")
            return rendered + suffix
    return f"{int(round(value)):,}"


def encounter_seconds(encounter):
    return max(1, int(round(float(getattr(encounter, "duration", 1) or 1))))


def sorted_attackers(encounter, attackers=None):
    values = list(attackers if attackers is not None else
                  getattr(encounter, "attackers", {}).values())
    return sorted(values, key=lambda item: item.damage, reverse=True)


def incoming_for_attacker(encounter, stats):
    names = {
        str(value).casefold()
        for value in getattr(stats, "source_names", {stats.name})
        if not str(value).casefold().endswith(" + pets")}
    if not names:
        names.add(str(stats.name).removesuffix(" + pets").casefold())
    tanks = [
        tank for name, tank in getattr(encounter, "tanks", {}).items()
        if str(name).casefold() in names]
    return sum(tank.damage for tank in tanks), max(
        (tank.max_hit for tank in tanks), default=0)


def _eq_player_piece(rank, stats, total, duration, options):
    fields = [f"#{rank} {stats.name}"]
    if options.get("show_damage", True):
        fields.append(compact_number(stats.damage))
    if options.get("show_percentage", True):
        fields.append(f"{stats.damage / max(1, total) * 100:.1f}%")
    suffix = "dps" if options.get("append_dps_label", False) else ""
    if options.get("show_dps", True):
        fields.append(
            f"{compact_number(stats.damage / max(1.0, stats.active_duration))}{suffix}")
    if options.get("show_sdps", True):
        fields.append(f"{compact_number(stats.damage / duration)}sdps")
    return " ".join(fields)


def eq_summary_lines(encounter, attackers=None, options=None, max_chars=240):
    """Return paste-ready EQ lines without ever interacting with the client."""
    options = dict(options or {})
    duration = float(encounter_seconds(encounter))
    total = max(0, int(getattr(encounter, "total_damage", 0) or 0))
    values = sorted_attackers(encounter, attackers)
    top = int(options.get("top_players", 10) or 10)
    if top > 0:
        values = values[:top]
    header = []
    if options.get("show_opponent", True):
        header.append(f"{encounter.target} in {int(duration)}s")
    if options.get("show_damage", True):
        header.append(f"DMG {compact_number(total)}")
    if options.get("show_sdps", True):
        header.append(f"{compact_number(total / duration)}sdps")
    separator = str(options.get("separator", " | ") or " | ")[:20]
    pieces = ([" ".join(header)] if header else []) + [
        _eq_player_piece(index, stats, total, duration, options)
        for index, stats in enumerate(values, 1)]
    channel = str(options.get("output_channel", "") or "").strip()
    prefix = f"{channel} " if channel else ""
    limit = max(80, min(500, int(max_chars)))
    lines = []
    current = prefix
    for piece in pieces:
        candidate = piece if current == prefix else separator + piece
        if current != prefix and len(current) + len(candidate) > limit:
            lines.append(current.rstrip())
            current = prefix + piece
        else:
            current += candidate
    if current.strip():
        lines.append(current.rstrip())
    return lines


def detailed_plain_text(encounter, attackers=None, options=None, version=""):
    """Produce the familiar detailed forum text while keeping claims honest."""
    options = dict(options or {})
    duration = encounter_seconds(encounter)
    total = max(0, int(getattr(encounter, "total_damage", 0) or 0))
    values = sorted_attackers(encounter, attackers)
    lines = [
        f"{encounter.target} on {encounter.started_at:%Y-%m-%d} in {duration}sec",
        "Total",
        (f"--- DMG: {total} @ {round(total / duration)} sdps "
         f"({round(total / duration)} dps in {duration}s) [100%]"),
    ]
    total_in = sum(stats.damage for stats in getattr(
        encounter, "tanks", {}).values())
    if total_in:
        lines.append(f"--- DMG to PC: {total_in} @{round(total_in / duration)}dps")
    for stats in values:
        active = max(1, int(round(stats.active_duration)))
        percent = stats.damage / max(1, total) * 100
        lines.extend((
            stats.name,
            (f"--- DMG: {stats.damage} @ {round(stats.damage / duration)} sdps "
             f"({round(stats.damage / active)} dps in {active}s) "
             f"[{percent:.2f}%]"),
        ))
        if options.get("plain_show_type", False) and stats.by_type:
            breakdown = " -- ".join(
                f"{item.name}: {item.damage}"
                for item in sorted(
                    stats.by_type.values(), key=lambda item: item.damage,
                    reverse=True))
            lines.append(f"------ Total: {stats.damage} -- {breakdown}")
        if options.get("plain_show_crit", False):
            normal = max(0, stats.hits - stats.criticals)
            lines.append(
                f"------ Critical hits: {stats.criticals} -- Normal hits: {normal}")
        if options.get("plain_show_accuracy", False):
            defended = max(0, stats.attempts - stats.hits - stats.misses)
            lines.append(
                f"------ Attempts: {stats.attempts} -- Hits: {stats.hits} -- "
                f"Misses: {stats.misses} -- Defended: {defended} -- "
                f"Accuracy: {stats.accuracy:.1f}%")
        damage_in, npc_max = incoming_for_attacker(encounter, stats)
        if damage_in:
            lines.append(
                f"--- DMG to PC: {damage_in} "
                f"@{round(damage_in / duration)}dps -- NPC Max: {npc_max}")
    lines.append("Produced by Vantage" + (f" v{version}" if version else ""))
    return "\n".join(lines)


def tabular_text(headers, rows):
    return "\n".join([
        "\t".join(str(value) for value in headers),
        *("\t".join(str(value) for value in row) for row in rows),
    ])


def bbcode_table(title, summary, headers, rows):
    def clean(value):
        return str(value).replace("[", "(").replace("]", ")")

    lines = [f"[b]{clean(title)}[/b]", clean(summary), "[table]"]
    lines.append("[tr]" + "".join(
        f"[th]{clean(value)}[/th]" for value in headers) + "[/tr]")
    lines.extend("[tr]" + "".join(
        f"[td]{clean(value)}[/td]" for value in row) + "[/tr]"
        for row in rows)
    lines.extend(("[/table]", "[i]Produced by Vantage[/i]"))
    return "\n".join(lines)


HTML_THEMES = {
    "dark": ("#101318", "#171B20", "#2A3038", "#E8E1D2", "#C8A96B"),
    "neutral": ("#F5F3EE", "#FFFFFF", "#D9D4C8", "#292721", "#72582D"),
    "slate": ("#182027", "#222C34", "#3A4650", "#E4E8EA", "#83A9B8"),
}


def html_report(title, summary, sections, options=None):
    options = dict(options or {})
    theme = HTML_THEMES.get(options.get("html_theme", "dark"),
                            HTML_THEMES["dark"])
    background, cell, border, text, accent = theme
    font_size = {"small": 12, "medium": 14, "large": 16}.get(
        options.get("html_font_size", "small"), 12)
    truncate = 40 if options.get("html_truncate", False) else 0
    chunks = ["<!doctype html><html><head><meta charset='utf-8'>",
              f"<title>{escape(str(title))}</title>", "<style>",
              ("body{font-family:Segoe UI,Arial,sans-serif;margin:24px;"
               f"background:{background};color:{text};font-size:{font_size}px}}"),
              f"h1,h2{{color:{accent};margin:14px 0 8px}}",
              "h1{font-size:1.45em}h2{font-size:1.15em}",
              (f"table{{border-collapse:collapse;width:100%;background:{cell};"
               "margin:8px 0 18px}}"),
              (f"th,td{{border:1px solid {border};padding:5px 7px;"
               "text-align:right;white-space:nowrap}}"),
              f"th{{color:{accent};text-align:right}}th:first-child,td:first-child{{text-align:left}}",
              ".meta{opacity:.82}.footer{opacity:.65;margin-top:24px}",
              "</style></head><body>", f"<h1>{escape(str(title))}</h1>",
              f"<p class='meta'>{escape(str(summary))}</p>"]
    for section_title, headers, rows in sections:
        visible_rows = list(rows[:truncate] if truncate else rows)
        chunks.extend((f"<h2>{escape(str(section_title))}</h2>", "<table><thead><tr>"))
        chunks.extend(f"<th>{escape(str(value))}</th>" for value in headers)
        chunks.append("</tr></thead><tbody>")
        for row in visible_rows:
            chunks.append("<tr>")
            chunks.extend(f"<td>{escape(str(value))}</td>" for value in row)
            chunks.append("</tr>")
        chunks.append("</tbody></table>")
    chunks.extend(("<p class='footer'>Produced by Vantage</p>", "</body></html>"))
    return "".join(chunks)


def xml_report(title, summary, sections):
    root = ET.Element("vantage-combat-report")
    ET.SubElement(root, "title").text = str(title)
    ET.SubElement(root, "summary").text = str(summary)
    for section_title, headers, rows in sections:
        section = ET.SubElement(root, "section", name=str(section_title))
        for row in rows:
            row_node = ET.SubElement(section, "row")
            for header, value in zip(headers, row):
                field = ET.SubElement(row_node, "field", name=str(header))
                field.text = str(value)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)
