"""Chat client geometry, not a simulation of Titanium's text/scroll renderer."""
from hashlib import sha256
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

SKIN = Path(__file__).resolve().parents[1] / 'ui' / 'skin'
CHAT_NATIVE_BASELINE = '9ead43f33be6cfa32ec1ebeeabf553792bb977fb5f0c96ddf637f70e2989f204'
OUTPUT_FIELDS = ('TopAnchorOffset', 'RightAnchorOffset', 'BottomAnchorOffset')


def xml(filename):
    return ET.parse(SKIN / filename).getroot()


def modeled_client_size(width, height):
    """Static inset model from ChatWindow's frame/titlebar texture spans."""
    chat = xml('EQUI_ChatWindow.xml')
    window = chat.find("Screen[@item='ChatWindow']")
    templates = xml('EQUI_Templates.xml')
    template = templates.find(f"WindowDrawTemplate[@item='{window.findtext('DrawTemplate')}']")
    animations = xml('EQUI_Animations.xml')
    def span(reference, dimension):
        frame = animations.find(f"Ui2DAnimation[@item='{reference}']/Frames")
        return int(frame.findtext('Size/' + dimension))
    left = span(template.findtext('Border/Left'), 'CX')
    right = span(template.findtext('Border/Right'), 'CX')
    top = span(template.findtext('Border/Top'), 'CY')
    bottom = span(template.findtext('Border/Bottom'), 'CY')
    title = span(template.findtext('Titlebar/Middle'), 'CY')
    assert (left, right, top, bottom, title) == (4, 4, 4, 4, 16)
    return width - left - right, height - top - bottom - title


def anchored_rect(node, width, height):
    return (int(node.findtext('LeftAnchorOffset')),
            int(node.findtext('TopAnchorOffset')) if node.findtext('TopAnchorToTop') != 'false'
            else height - int(node.findtext('TopAnchorOffset')),
            width - int(node.findtext('RightAnchorOffset')),
            height - int(node.findtext('BottomAnchorOffset')))


@pytest.mark.parametrize('outer_width,outer_height', (
    (144, 120), (250, 150), (299, 222), (421, 200),
    (579, 221), (900, 600), (1280, 720),
))
def test_chat_clearance_fits_the_modeled_client_when_resized(outer_width, outer_height):
    chat = xml('EQUI_ChatWindow.xml')
    output = chat.find("STMLbox[@item='CW_ChatOutput']")
    entry = chat.find("Editbox[@item='CW_ChatInput']")
    width, height = modeled_client_size(outer_width, outer_height)
    ox, oy, oright, obottom = anchored_rect(output, width, height)
    ix, iy, iright, ibottom = anchored_rect(entry, width, height)
    assert ox == 10 and oy == 6
    assert width - oright == width - iright == 6
    assert iy - obottom == 6
    assert ibottom - iy == 21 and height - ibottom == ix == 6
    assert 0 <= ox < oright <= width and 0 <= oy < obottom < iy < ibottom <= height
    assert 0 <= ix < iright <= width
    assert output.findtext('Style_VScroll') == 'true'
    assert entry.findtext('AutoStretch') == output.findtext('AutoStretch') == 'true'
    assert output.find('Font') is None and entry.find('Font') is None


def test_padding_delta_preserves_every_other_native_chat_field_and_default():
    chat = xml('EQUI_ChatWindow.xml')
    output = chat.find("STMLbox[@item='CW_ChatOutput']")
    assert [output.findtext(field) for field in OUTPUT_FIELDS] == ['6', '6', '33']
    for field in OUTPUT_FIELDS:
        output.remove(output.find(field))
    canonical = ET.canonicalize(ET.tostring(chat, encoding='unicode'), strip_text=True)
    assert sha256(canonical.encode()).hexdigest() == CHAT_NATIVE_BASELINE
