"""Curated classic-era weapon presets for the local threat estimator."""


def _weapon(name, aliases, damage, delay, weapon_type, bonus=0,
            proc_threat=0, resisted='', landed=''):
    return {
        'name': name,
        'aliases': tuple(aliases),
        'type': weapon_type,
        'damage': damage,
        'delay': delay,
        'damage_bonus': bonus,
        'proc_threat': proc_threat,
        'proc_resisted': resisted,
        'proc_landed': landed,
    }


WEAPON_PRESETS = (
    _weapon('Hand to Hand', ('h2h', 'hand', 'hands'), 4, 36, 'h2h'),
    _weapon('Monk Epic Fist', ('monkfist', 'epicfist', 'monkepic'), 9, 16, 'h2h'),
    _weapon(
        'Blade of Strategy', ('red', 'redblade', 'redepic'), 14, 24, '1hs',
        proc_threat=600,
        resisted='Your target resisted the Rage of Vallon',
        landed='{target} is weakened by the Rage of Vallon.'),
    _weapon(
        'Howling Cutlass', ('hc', 'howlingcutlass', 'cutlass'), 10, 19, '1hs',
        proc_threat=520,
        resisted='Your target resisted the Shrieking Howl',
        landed='{target} is deafened.'),
    _weapon('Blade of Tactics', ('blue', 'blueblade', 'blueepic'), 14, 24, '1hs'),
    _weapon('Swiftblade of Zek', ('swiftblade', 'swift', 'sboz'), 11, 18, '1hs'),
    _weapon('Hammer of Battle', ('statuehammer', 'hammerofbattle', 'hob'), 17, 25, '1hb'),
    _weapon('Primal Velium Fist Wraps', ('primalfist', 'pvfw', 'pf'), 15, 20, '1hb'),
    _weapon('Whitestone Shield', ('whitestone', 'shield', 'wss'), 0, 1000, 'shield'),
    _weapon(
        'Jagged Blade of War', ('2hepic', 'redblue', 'jbow'), 36, 41, '2hs', 34,
        proc_threat=675,
        resisted='Your target resisted the Rage of Zek',
        landed="{target}'s soul is consumed by the fury of Zek."),
    _weapon('Primal Velium Claidhmore', ('2hsprimal', 'primal2hs', 'pvc'),
            45, 44, '2hs', 37),
    _weapon('The Horn of Hsagra', ('ktdagger', 'ktd', 'thoh'), 13, 20, '1hp'),
    _weapon('Ragebringer', ('rogepic', 'rogueepic', 'rage'), 15, 25, '1hp'),
    _weapon('Priceless Velium Spear', ('1hpprimal', 'primalspear', 'pvs'),
            13, 20, '1hp'),
    _weapon('Primal Velium Warsword', ('1hsprimal', 'warsword', 'pvw'),
            13, 20, '1hs'),
    _weapon(
        'Trident of the Deep Sea', ('trident', 'koitrident', 'tods'),
        14, 22, '1hp', proc_threat=400,
        resisted='Your target resisted the Waves of the Deep Sea',
        landed='{target} is crushed by a wall of water.'),
    _weapon(
        'Willsapper', ('willsapper', 'ws', 'vaniki'), 13, 20, '1hp',
        proc_threat=400, resisted='Your target resisted the Energy Sap',
        landed='{target} yawns.'),
    _weapon('Swiftwind', ('sw', 'wind', 'roe'), 13, 21, '1hs'),
    _weapon(
        'Earthcaller', ('earth', 'ec', 'rme'), 14, 24, '1hs',
        proc_threat=400, resisted='Your target resisted the Earthcall',
        landed='{target} is slowed by the embracing earth.'),
    _weapon(
        'Wrapped Entropy Serpent Spine', ('wess',), 11, 23, '1hs',
        proc_threat=800,
        resisted='Your target resisted the Blinding Poison III spell',
        landed='{target} staggers around blindly.'),
    _weapon('Axe of Resistance', ('axe', 'aor'), 15, 24, '1hs'),
    _weapon(
        "Jaelen's Katana", ('jaelen', 'katana', 'jk'), 14, 19, '1hs',
        proc_threat=120,
        resisted='Your target resisted the Strike of the Chosen',
        landed="says 'Ahhh, I feel much better now...'"),
)


def find_weapon_preset(value):
    """Resolve a display name or a compact player alias."""
    folded = str(value or '').strip().replace(' ', '').replace('_', '').casefold()
    if not folded:
        return None
    for preset in WEAPON_PRESETS:
        names = (preset['name'], *preset['aliases'])
        if any(
                folded == str(name).replace(' ', '').replace('_', '').casefold()
                for name in names):
            return preset
    return None
