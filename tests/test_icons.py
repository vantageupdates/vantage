from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


def test_shared_svg_icons_are_valid_attributed_vector_assets():
    icons = sorted((ROOT / "data" / "ui" / "icons").glob("*.svg"))
    assert len(icons) >= 30
    for icon in icons:
        source = icon.read_text(encoding="utf-8")
        root = ET.fromstring(source)
        assert root.attrib["viewBox"]
        assert "var(--ci-" not in source
        if icon.name.startswith("ph-"):
            assert root.attrib["viewBox"] == "0 0 256 256"
            if icon.name.startswith("ph-coffee-"):
                assert any(color in source for color in ("#D0B675", "#FFE09A"))
            elif icon.name.startswith("ph-pulse-online-"):
                assert any(color in source for color in ("#55C785", "#8EF0B8"))
            else:
                assert "#D0B675" in source
        else:
            assert root.attrib["data-icon-source"] == "CoreUI Icons Free"

    coreui_license = (
        ROOT / "data" / "ui" / "icons" / "COREUI-LICENSE.txt"
    ).read_text(encoding="utf-8")
    phosphor_license = (
        ROOT / "data" / "ui" / "icons" / "PHOSPHOR-LICENSE.txt"
    ).read_text(encoding="utf-8")
    assert "CC BY 4.0" in coreui_license
    assert "MIT License" in phosphor_license
    assert "Phosphor Icons" in phosphor_license
