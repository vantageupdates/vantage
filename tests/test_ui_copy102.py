"""English control help must not change native commands, geometry or states."""
from hashlib import sha256
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

SKIN = Path(__file__).resolve().parents[1] / 'ui' / 'skin'
FILTERS = ('Red', 'Yellow', 'White', 'Blue', 'LightBlue', 'Green')
NATIVE_BASELINES = {
    'EQUI_TrackingWnd.xml': (
        tuple('TRW_Filter' + color + 'Button' for color in FILTERS),
        'dbd332492baba75d6f9361dd96df7dfe8187dd2aeb6be14d0dd434cc263e2df9'),
    'EQUI_OptionsWindow.xml': (
        ('OGP_ChangeFont',),
        '49f178003675bec7aa84a9625efd109677b5cf8079a207ff28c422c19fcc8b28'),
    'EQUI_PetInfoWindow.xml': (
        ('PIW_LostButton',),
        '07791c25d58388f2ea9e7fe2d46f34d7c2a5ec87abbd176314a1a25a79648795'),
    'EQUI_RaidWindow.xml': (
        ('RAID_DeclineButton',),
        '99a10deff18030498d342a3b5af26540c560596fc253a4af8973aca1b7872c4e'),
    'EQUI_GuildManagementWnd.xml': (
        ('GT_PromoteButton',),
        'd8d90ec24f2aaecfbd0be3a03384c8d93adf56e79ae059c73d4f4c294c8d2607'),
}


def root(filename):
    return ET.parse(SKIN / filename).getroot()


@pytest.mark.parametrize('filename', NATIVE_BASELINES)
def test_copy_edits_preserve_every_other_native_field(filename):
    # Canonical 1.44.101 trees, excluding only the reviewed text/help fields.
    names, baseline = NATIVE_BASELINES[filename]
    tree = root(filename)
    for button in tree.findall('Button'):
        if button.get('item') in names:
            for tag in ('Text', 'TooltipReference'):
                field = button.find(tag)
                if field is not None:
                    button.remove(field)
    canonical = ET.canonicalize(ET.tostring(tree, encoding='unicode'), strip_text=True)
    assert sha256(canonical.encode()).hexdigest() == baseline


@pytest.mark.parametrize('index,color', tuple(enumerate(FILTERS)))
def test_tracking_filters_keep_compact_captions_and_add_full_color_help(index, color):
    button = root('EQUI_TrackingWnd.xml').find(f"Button[@item='TRW_Filter{color}Button']")
    assert button.findtext('Text') == 'RYWBLG'[index]
    readable_color = 'Light-blue' if color == 'LightBlue' else color
    assert button.findtext('TooltipReference') == readable_color + ' targets'
    assert button.findtext('Style_Checkbox') == 'true'


def test_font_apply_help_is_clear_without_claiming_unverified_scope():
    button = root('EQUI_OptionsWindow.xml').find("Button[@item='OGP_ChangeFont']")
    assert button.findtext('Text') == 'Apply'
    assert button.findtext('TooltipReference') == 'Apply the selected font.'


def test_pet_help_makes_dismissal_clear_without_changing_native_caption():
    button = root('EQUI_PetInfoWindow.xml').find("Button[@item='PIW_LostButton']")
    assert button.findtext('Text') == 'Go Away'
    assert button.findtext('TooltipReference') == 'Dismiss your pet.'


@pytest.mark.parametrize('filename,name,word', (
    ('EQUI_RaidWindow.xml', 'RAID_DeclineButton', 'invitation'),
    ('EQUI_GuildManagementWnd.xml', 'GT_PromoteButton', 'targeted'),
))
def test_help_spelling_is_correct(filename, name, word):
    tooltip = root(filename).find(f"Button[@item='{name}']").findtext('TooltipReference')
    assert word in tooltip
    assert 'invtitation' not in tooltip and 'targetted' not in tooltip
