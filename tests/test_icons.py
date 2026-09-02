from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


def test_shared_svg_icons_use_the_attributed_coreui_vector_system():
    icons = sorted((ROOT / "data" / "ui" / "icons").glob("*.svg"))
    assert len(icons) >= 30
    for icon in icons:
        source = icon.read_text(encoding="utf-8")
        root = ET.fromstring(source)
        assert root.attrib["data-icon-source"] == "CoreUI Icons Free"
        assert root.attrib["viewBox"]
        assert "var(--ci-" not in source

    license_text = (
        ROOT / "data" / "ui" / "icons" / "COREUI-LICENSE.txt"
    ).read_text(encoding="utf-8")
    assert "CC BY 4.0" in license_text
