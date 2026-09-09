"""Options-only styling and binding regressions. Native EQ interaction is manual."""
import hashlib
from itertools import combinations
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

SKIN = Path(__file__).resolve().parents[1] / 'ui' / 'skin'
ROOT = ET.parse(SKIN / 'EQUI_OptionsWindow.xml').getroot()
CELLS = [(2, 2, 150, 18, 22), (156, 2, 150, 16, 22),
         (310, 2, 50, 22, 26), (2, 124, 150, 20, 24), (364, 2, 26, 22, 26)]
STATES = ('Normal', 'Flyby', 'Pressed', 'PressedFlyby', 'Disabled')


def pixel(x, y):
    data = (SKIN / 'VantageOptionsControls.tga').read_bytes()
    pos = 18 + 4 * (512 * y + x)
    return tuple(data[pos:pos + 4])


@pytest.mark.parametrize('cell', CELLS)
def test_options_native_size_frames_clear_rounded_corners_and_keep_distinct_states(cell):
    x, y, w, h, stride = cell
    centers = []
    for i, state in enumerate(STATES):
        frame = ROOT.find(f"Ui2DAnimation[@item='A_VantageOpt{w}x{h}{state}']/Frames")
        assert frame.findtext('Texture') == 'VantageOptionsControls.tga'
        assert tuple(int(frame.findtext(p)) for p in ('Location/X', 'Location/Y', 'Size/CX', 'Size/CY')) == (x, y + i * stride, w, h)
        top = y + i * stride
        assert all(pixel(x + dx, top + dy) == (0, 0, 0, 0)
                   for dx in (0, w - 1) for dy in (0, h - 1))
        assert len({pixel(x + dx, top + dy)[3] for dx in range(6) for dy in range(6)} - {0, 255}) > 3
        centers.append(pixel(x + w // 2, top + h // 2))
        assert all(pixel(xx, yy) == (0, 0, 0, 0)
                   for xx in range(x - 1, x + w + 1) for yy in (top - 1, top + h))
    assert len(set(centers)) == 5
    assert all(b == g == r and a == 255 for b, g, r, a in centers)
    assert centers[2][0] > centers[0][0]  # Persistent pressed/checked cue.


def test_every_options_button_keeps_its_native_checkbox_semantics_and_art_size():
    styled = ROOT.findall('Button')
    changed = [b for b in styled if b.findtext('ButtonDrawTemplate/Normal', '').startswith('A_VantageOpt')]
    assert len(changed) == 41
    for button in changed:
        assert button.findtext('Style_Transparent') == 'true'
        assert button.findtext('Style_Border') == 'false'
        assert button.findtext('Font') == '2'
        assert len(button.findall('Font')) == 1
        assert button.findtext('ScreenID')
        for state in STATES:
            art = button.findtext('ButtonDrawTemplate/' + state)
            assert ROOT.find(f"Ui2DAnimation[@item='{art}']") is not None
        if button.find('Size') is not None:
            w = button.findtext('Size/CX'); h = button.findtext('Size/CY')
            assert button.findtext('ButtonDrawTemplate/Normal') == f'A_VantageOpt{w}x{h}Normal'
    # These controls are real small checkboxes, not converted into new actions.
    for button in styled:
        if button not in changed:
            assert button.findtext('Style_Checkbox') == 'true'
            assert button.findtext('ButtonDrawTemplate/Normal') == 'A_CheckBoxNormal'


@pytest.mark.parametrize('page_name', ['OptionsGeneralPage', 'OptionsDisplayPage', 'OptionsMousePage'])
def test_same_page_buttons_have_gutters_not_touching_faces(page_name):
    page = ROOT.find(f"Page[@item='{page_name}']")
    controls = []
    for piece in page.findall('Pieces'):
        b = ROOT.find(f"Button[@item='{piece.text}']")
        if b is not None and b.find('Location') is not None:
            box = tuple(int(b.findtext(p)) for p in ('Location/X', 'Location/Y', 'Size/CX', 'Size/CY'))
            controls.append((b.attrib['item'], box))
    for (name_a, (ax, ay, aw, ah)), (name_b, (bx, by, bw, bh)) in combinations(controls, 2):
        if {name_a, name_b} == {'ODP_SetFullscreenButton', 'ODP_SetWindowedButton'}:
            assert (ax, ay, aw, ah) == (bx, by, bw, bh)  # Native exclusive states.
            continue
        if ax < bx + bw and bx < ax + aw:
            assert ay + ah + 2 <= by or by + bh + 2 <= ay, (name_a, name_b)


def test_options_preserves_root_size_tabs_and_neutral_gold_selection():
    window = ROOT.find("Screen[@item='OptionsWindow']")
    assert tuple(int(window.findtext(p)) for p in ('Location/X', 'Location/Y', 'Size/CX', 'Size/CY')) == (90, 47, 390, 450)
    assert [p.text for p in ROOT.find("TabBox[@item='OPTW_OptionsSubwindows']").findall('Pages')] == [
        'OptionsGeneralPage', 'OptionsDisplayPage', 'OptionsMousePage', 'OptionsKeyboardPage',
        'OptionsChatPage', 'OptionsColorPage', 'OptionsMailPage']
    for page in ROOT.findall('Page'):
        assert tuple(int(page.findtext('TabTextActiveColor/' + c)) for c in 'RGB') == (218, 195, 147)
        assert tuple(int(page.findtext('TabTextColor/' + c)) for c in 'RGB') == (180, 180, 180)
    for kind in ('Combobox', 'Editbox', 'Listbox'):
        assert all(n.findtext('DrawTemplate') == 'WDT_VantageOptionsField' for n in ROOT.findall(kind))


def test_fine_options_field_border_preserves_background_scrollbars_and_chrome():
    templates = ET.parse(SKIN / 'EQUI_Templates.xml').getroot()
    original = templates.find("WindowDrawTemplate[@item='WDT_Inner']")
    field = ROOT.find("WindowDrawTemplate[@item='WDT_VantageOptionsField']")
    def shape(node):
        return (node.tag, tuple(node.attrib.items()), (node.text or '').strip(), tuple(shape(c) for c in node))
    assert [shape(n) for n in field if n.tag != 'Border'] == [shape(n) for n in original if n.tag != 'Border']
    assert shape(field.find('Border')) == shape(templates.find("WindowDrawTemplate[@item='WDT_VantageSlotGold']/Border"))
    assert field.find('VSBTemplate') is not None
    assert field.find('HSBTemplate') is not None
    assert field.findtext('Background') == original.findtext('Background')


def native_contract(xml):
    """Ignore only the reviewed visual delta, preserving all remaining XML."""
    def shape(node):
        return (node.tag, tuple(sorted(node.attrib.items())), (node.text or '').strip(), tuple(shape(c) for c in node))
    for node in list(xml):
        if node.tag in ('TextureInfo', 'Ui2DAnimation', 'WindowDrawTemplate') and 'VantageOpt' in node.attrib.get('item', ''):
            xml.remove(node)
            continue
        fields = []
        if node.tag == 'Button' and node.findtext('ButtonDrawTemplate/Normal', '').startswith(('A_Btn', 'A_SmallBtn', 'A_VantageOpt')):
            fields = ['Font', 'Style_Transparent', 'Style_Border', 'ButtonDrawTemplate',
                      'Location/Y', 'Size/CY', 'TopAnchorOffset', 'BottomAnchorOffset']
        if node.tag == 'Page':
            fields = ['TabTextColor', 'TabTextActiveColor']
        if node.tag in ('Combobox', 'Editbox', 'Listbox'):
            fields = ['DrawTemplate']
        for field in fields:
            child = node.find(field)
            if child is not None:
                parent = node.find(field.rsplit('/', 1)[0]) if '/' in field else node
                parent.remove(child)
    return hashlib.sha256(repr(shape(xml)).encode()).hexdigest()


def test_options_all_other_native_bindings_and_settings_are_unchanged():
    assert native_contract(ET.parse(SKIN / 'EQUI_OptionsWindow.xml').getroot()) == '0aee10eda2a9f879b2bd4ac9db5abe62e289a4e47e8185e02875d584d5984372'
