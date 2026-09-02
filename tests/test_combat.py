import datetime

from vantage.helpers.combat import CombatTracker, RandomEvent, build_random_sets


def at(seconds):
    return datetime.datetime(2026, 1, 1) + datetime.timedelta(seconds=seconds)


def test_parses_melee_and_non_melee_damage():
    tracker = CombatTracker()
    tracker.ingest(at(0), "You hit a fire beetle for 12 points of damage.")
    tracker.ingest(at(2), "a fire beetle was hit by non-melee for 20 points of damage.")
    encounter = tracker.current()
    assert encounter.target == "a fire beetle"
    assert encounter.total_damage == 32
    assert encounter.attackers['You'].hits == 2


def test_kill_finalizes_encounter():
    tracker = CombatTracker()
    tracker.ingest(at(0), "You have entered Lower Guk.")
    tracker.ingest(at(0), "You slash a goblin for 10 points of damage.")
    tracker.ingest(at(3), "You have slain a goblin!")
    assert tracker.current() is None
    assert tracker.last().killed is True
    assert tracker.last().target == "a goblin"
    assert tracker.last().zone == "Lower Guk"
    assert tracker.last().player_count == 1
    assert round(tracker.last().your_dps, 1) == 10.0


def test_session_aggregates_attackers():
    tracker = CombatTracker()
    tracker.ingest(at(0), "Alice hits a bat for 9 points of damage.")
    tracker.ingest(at(1), "You hit a bat for 11 points of damage.")
    assert tracker.session_attackers['Alice'].damage == 9
    assert tracker.session_attackers['You'].damage == 11


def test_tracks_attempts_accuracy_attack_types_and_active_dps():
    tracker = CombatTracker()
    tracker.ingest(at(0), "You try to slash a bat, but miss!")
    tracker.ingest(at(2), "You slash a bat for 15 points of damage.")
    tracker.ingest(at(5), "You kick a bat for 7 points of damage.")

    stats = tracker.current().attackers["You"]
    assert stats.attempts == 3
    assert stats.hits == 2
    assert round(stats.accuracy, 1) == 66.7
    assert stats.min_hit == 7
    assert stats.max_hit == 15
    assert stats.by_type["Slashing"].damage == 15
    assert stats.by_type["Kick"].damage == 7
    # GamParse QuickDPS ignores misses and uses inclusive hit time.
    assert stats.active_duration == 4


def test_tracks_gamparse_damage_to_pc_for_visible_group_member():
    tracker = CombatTracker()
    tracker.ingest(at(0), "Alice slashes a goblin for 20 points of damage.")
    tracker.ingest(at(1), "a goblin hits Alice for 7 points of damage.")
    tracker.ingest(at(2), "a goblin crushes You for 11 points of damage.")

    encounter = tracker.current()
    assert encounter.target == "a goblin"
    assert encounter.total_damage == 20
    assert encounter.tanks["Alice"].damage == 7
    assert encounter.tanks["Alice"].max_hit == 7
    assert encounter.tanks["You"].damage == 11


def test_tracks_spells_resists_healing_and_tanking_visible_in_log():
    tracker = CombatTracker()
    tracker.ingest(at(0), "You begin casting Ignite.")
    tracker.ingest(at(1), "a goblin was hit by non-melee for 40 points of damage.")
    tracker.ingest(at(2), "Your target resisted the Ignite spell.")
    tracker.ingest(at(3), "You healed Bob for 25 hit points.")
    tracker.ingest(at(4), "a goblin hits You for 12 points of damage.")

    goblin = tracker.active["a goblin"]
    assert goblin.spells["Ignite"].casts == 1
    assert goblin.spells["Ignite"].damage == 40
    assert goblin.spells["Ignite"].resists == 1
    assert goblin.healers["You"].healing == 25
    assert goblin.healers["You"].by_target["Bob"]["healing"] == 25
    incoming = tracker.active["a goblin"]
    assert incoming.tanks["You"].damage == 12
    assert incoming.total_damage == 40


def test_separates_direct_spell_damage_from_dot_ticks():
    tracker = CombatTracker()
    tracker.ingest(at(0), "You begin casting Ignite.")
    tracker.ingest(
        at(1), "a goblin was hit by non-melee for 40 points of damage.")
    tracker.ingest(
        at(2), "a goblin has taken 7 damage from your Flame Lick.")
    tracker.ingest(
        at(3), "a goblin has taken 9 damage from your Flame Lick.")

    ignite = tracker.current().spells["Ignite"]
    flame_lick = tracker.current().spells["Flame Lick"]
    assert (ignite.direct_damage, ignite.direct_hits, ignite.direct_max) == (
        40, 1, 40)
    assert ignite.ticks == 0
    assert (flame_lick.dot_damage, flame_lick.dot_ticks, flame_lick.dot_max) == (
        16, 2, 9)
    assert flame_lick.direct_damage == 0


def test_tracks_gamparse_style_casters_outcomes_and_cast_timeline():
    tracker = CombatTracker()
    tracker.ingest(at(0), "You hit a giant for 1 point of damage.")
    tracker.ingest(at(1), "You begin casting Ignite.")
    tracker.ingest(at(2), "Your target resisted the Ignite spell.")
    tracker.ingest(at(3), "Alice begins casting Complete Heal.")
    tracker.ingest(at(4), "Alice's spell is interrupted.")
    tracker.ingest(at(5), "Cara begins casting Ice Comet.")
    tracker.ingest(
        at(6), "Cara's Ice Comet spell has been reflected by a giant.")
    tracker.ingest(at(7), "You begin casting Root.")
    tracker.ingest(at(8), "Your spell did not take hold.")

    fight = tracker.current()
    assert fight.caster_spells["You"]["Ignite"].resists == 1
    assert fight.caster_spells["You"]["Root"].blocks == 1
    assert fight.caster_spells["Alice"]["Complete Heal"].interrupts == 1
    assert fight.caster_spells["Cara"]["Ice Comet"].reflects == 1
    assert [record.outcome for record in fight.spell_casts] == [
        "Resist", "Interrupt", "Reflect", "Blocked"]
    assert [record.caster for record in fight.spell_casts] == [
        "You", "Alice", "Cara", "You"]


def test_parser_diagnostics_are_bounded_opt_in_and_exclude_chat():
    tracker = CombatTracker()
    tracker.ingest(at(0), "You hit a bat for 3 points of damage.")
    assert list(tracker.diagnostics) == []

    tracker.set_diagnostics_enabled(True)
    tracker.ingest(at(1), "You slash a bat for 12 points of damage.")
    tracker.ingest(at(2), "a bat dodges You's attack!")
    tracker.ingest(at(3), "You begin casting Ignite.")
    tracker.ingest(at(4), "a bat was hit by non-melee for 40 points of damage.")
    tracker.ingest(at(5), "a bat has taken 7 damage from your Flame Lick.")
    tracker.ingest(at(6), "You healed Bob for 25 hit points.")
    tracker.ingest(at(6.5), "Cleric has healed you for 30 hit points!")
    tracker.ingest(at(7), "Trader tells you, 'that spell hit hard'")

    categories = [record.category for record in tracker.diagnostics]
    assert categories == [
        "Healing", "Healing", "DoT", "Direct Damage", "Spells", "Defense",
        "Melee"]
    assert all("Trader tells you" not in record.source
               for record in tracker.diagnostics)
    assert tracker.diagnostics[-1].action == "Slashing"
    assert tracker.diagnostics[-1].amount == 12
    assert tracker.diagnostics[0].actor == "Cleric"
    assert tracker.diagnostics[0].target == "you"
    assert tracker.diagnostics[2].action == "Flame Lick"

    tracker.ingest(at(8), "Your spell glimmers strangely.")
    assert tracker.diagnostics[0].category == "Unmatched"
    assert tracker.clear_diagnostics() is True
    assert tracker.clear_diagnostics() is False


def test_damage_mods_require_a_nearby_reported_critical_and_real_hit():
    tracker = CombatTracker()
    tracker.ingest(at(0), "You hit a giant for 1 point of damage.")
    tracker.ingest(at(1), "You score a critical hit! (100)")
    tracker.ingest(at(2), "You slash a giant for 125 points of damage.")
    tracker.ingest(at(3), "You land a Crippling Blow!! (200)")
    tracker.ingest(at(4), "You crush a giant for 150 points of damage.")
    tracker.ingest(at(5), "You score a critical hit! (999)")
    tracker.ingest(at(12), "You kick a giant for 20 points of damage.")

    stats = tracker.current().attackers["You"]
    slash = stats.damage_modifiers[("Slashing", "Critical")]
    crush = stats.damage_modifiers[("Crushing", "Crippling")]
    assert (slash.samples, slash.reported_average, slash.actual_average) == (
        1, 100, 125)
    assert slash.modifier_percent == 25
    assert crush.modifier_percent == -25
    assert ("Kick", "Critical") not in stats.damage_modifiers
    assert stats.critical_types == {"Critical": 1, "Crippling": 1}


def test_combines_selected_fights_without_losing_player_breakdown():
    tracker = CombatTracker()
    tracker.ingest(at(0), "Alice hits a bat for 9 points of damage.")
    tracker.ingest(at(1), "You have slain a bat!")
    tracker.ingest(at(2), "Alice hits a rat for 11 points of damage.")
    tracker.ingest(at(4), "You have slain a rat!")

    combined = tracker.combine(list(tracker.completed), "Two fights")
    assert combined.target == "Two fights"
    assert combined.total_damage == 20
    assert combined.attackers["Alice"].hits == 2
    assert combined.killed is True


def test_combining_fights_preserves_caster_outcomes_and_damage_mod_samples():
    tracker = CombatTracker()
    for offset, target in ((0, "a bat"), (10, "a rat")):
        tracker.ingest(
            at(offset), f"You hit {target} for 1 point of damage.")
        tracker.ingest(at(offset + 1), "You begin casting Ignite.")
        if offset == 0:
            tracker.ingest(at(offset + 2), "Your spell fizzles!")
        tracker.ingest(at(offset + 3), "You score a critical hit! (100)")
        tracker.ingest(
            at(offset + 4), f"You slash {target} for 120 points of damage.")
        tracker.ingest(at(offset + 5), f"You have slain {target}!")

    combined = tracker.combine(list(tracker.completed), "Combined")
    ignite = combined.caster_spells["You"]["Ignite"]
    modifier = combined.attackers["You"].damage_modifiers[
        ("Slashing", "Critical")]
    assert (ignite.casts, ignite.fizzles) == (2, 1)
    assert len(combined.spell_casts) == 2
    assert modifier.samples == 2
    assert round(modifier.modifier_percent, 1) == 20


def test_manual_combine_rename_and_undo_preserve_original_fights():
    tracker = CombatTracker()
    tracker.ingest(at(0), "Alice hits a bat for 9 points of damage.")
    tracker.ingest(at(1), "You have slain a bat!")
    tracker.ingest(at(2), "Alice hits a rat for 11 points of damage.")
    tracker.ingest(at(4), "You have slain a rat!")

    combined = tracker.combine_completed([0, 1], "Two fights")
    assert len(combined) == 1
    assert len(tracker.completed) == 1
    assert tracker.last().target == "Two fights"
    assert tracker.last().total_damage == 20
    assert tracker.can_undo_completed_change is True

    assert tracker.rename_completed(0, "Renamed raid") is True
    assert tracker.last().target == "Renamed raid"
    assert tracker.undo_completed_change() is True
    assert tracker.last().target == "Two fights"
    assert tracker.undo_completed_change() is True
    assert [fight.target for fight in tracker.completed] == ["a rat", "a bat"]


def test_manual_combine_by_target_leaves_unmatched_fights_alone():
    tracker = CombatTracker()
    for offset, target, damage in (
            (0, "a bat", 5), (2, "a bat", 7), (4, "a rat", 11)):
        tracker.ingest(
            at(offset), f"You hit {target} for {damage} points of damage.")
        tracker.ingest(at(offset + 1), f"You have slain {target}!")

    combined = tracker.combine_completed([0, 1, 2], by_target=True)

    assert len(combined) == 1
    assert combined[0].target == "a bat · 2 fights"
    assert combined[0].total_damage == 12
    assert sorted(fight.target for fight in tracker.completed) == [
        "a bat · 2 fights", "a rat"]


def test_manual_delete_preserves_the_completed_memory_limit():
    tracker = CombatTracker(max_history=2)
    for offset, target in ((0, "a bat"), (2, "a rat")):
        tracker.ingest(at(offset), f"You hit {target} for 5 points of damage.")
        tracker.ingest(at(offset + 1), f"You have slain {target}!")

    assert tracker.delete_completed([0])
    assert tracker.completed.maxlen == 2


def test_keeps_bounded_chat_and_loot_activity():
    tracker = CombatTracker()
    tracker.ingest(at(0), "Trader auctions, 'WTS FBSS 12k'")
    tracker.ingest(at(1), "--You have looted a Fine Steel Sword.--")

    assert tracker.chat[-1].speaker == "Trader"
    assert tracker.chat[-1].channel.casefold() == "auction"
    assert tracker.chat[-1].message == "WTS FBSS 12k"
    assert tracker.loot[-1].looter == "You"
    assert tracker.loot[-1].item == "Fine Steel Sword"
    assert tracker.loot[-1].count == 1


def test_tracks_main_joined_channels_and_individual_tell_threads():
    tracker = CombatTracker()
    lines = (
        "You auction, 'WTS Runed Oak Bow 50p'",
        "Alice tells the raid, 'Assist now'",
        "Brielle tells the fellowship, 'Camp is ready'",
        "Cara tells General:1, 'Port available'",
        "Doran tells you, 'Incoming tell'",
        "You told Elowen, 'Outgoing tell'",
    )
    for offset, line in enumerate(lines):
        tracker.ingest(at(offset), line)

    channels = {event.message: event.channel for event in tracker.chat}
    assert channels == {
        "WTS Runed Oak Bow 50p": "Auction",
        "Assist now": "Raid",
        "Camp is ready": "Fellowship",
        "Port available": "General:1",
        "Incoming tell": "Tell · Doran",
        "Outgoing tell": "Tell · Elowen",
    }


def test_clearing_combat_can_preserve_independent_activity_history():
    tracker = CombatTracker()
    tracker.ingest(at(0), "Trader auctions, 'WTS FBSS 12k'")
    tracker.ingest(at(1), "You hit a rat for 10 points of damage.")
    tracker.reset_session(include_activity=False)

    assert len(tracker.chat) == 1
    assert not tracker.active
    assert not tracker.completed


def test_tracks_faction_and_random_roll_history():
    tracker = CombatTracker()
    tracker.ingest(at(0), "You have entered Kael Drakkel.")
    tracker.ingest(
        at(1), "Your faction standing with Claws of Veeshan got better.")
    tracker.ingest(at(2), "**A Magic Die is rolled by Alice.")
    tracker.ingest(
        at(3), "**It could have been any number from 0 to 1000, "
        "but this time it turned up 777.")

    assert tracker.faction[0].faction == "Claws of Veeshan"
    assert tracker.faction[0].change == "Got Better"
    assert tracker.faction[0].zone == "Kael Drakkel"
    assert tracker.randoms[0].player == "Alice"
    assert tracker.randoms[0].value == 777
    assert tracker.randoms[0].high == 1000


def test_tracks_loot_source_coin_totals_and_numeric_faction_changes():
    tracker = CombatTracker()
    tracker.ingest(at(0), "You have entered Velketor's Labyrinth.")
    tracker.ingest(
        at(1), "--You have looted 2 Crystalline Silk from a crystal spider.--")
    tracker.ingest(
        at(2), "You receive 3 platinum, 5 gold, 7 silver and 9 copper "
        "from the corpse.")
    tracker.ingest(
        at(3), "You receive 1 platinum, 2 silver as your split.")
    tracker.ingest(
        at(4), "Your faction standing with Claws of Veeshan has been "
        "adjusted by 5.")

    loot = tracker.loot[0]
    assert (loot.item, loot.count, loot.source, loot.zone) == (
        "Crystalline Silk", 2, "a crystal spider", "Velketor's Labyrinth")
    assert [event.kind for event in tracker.coins] == [
        "Group split", "Corpse"]
    assert sum(event.copper for event in tracker.coins) == 4599
    assert tracker.faction[0].change == "+5"
    assert tracker.faction[0].delta == 5


def test_random_sets_group_ranges_resolve_duplicates_and_find_winner():
    rolls = [
        RandomEvent(at(0), "Alice", 0, 1000, 300),
        RandomEvent(at(1), "Bob", 0, 1000, 800),
        RandomEvent(at(2), "Alice", 0, 1000, 900),
        RandomEvent(at(3), "Cara", 1, 100, 75),
        RandomEvent(at(25), "Dan", 0, 1000, 700),
    ]
    first = build_random_sets(rolls, "first", 20)
    assert len(first) == 3
    thousand = next(values for values in first if values["started"] == at(0))
    assert thousand["rolls"] == 3
    assert thousand["players"] == 2
    assert thousand["duplicates"] == 1
    assert thousand["winner"] == "Bob"
    highest = build_random_sets(rolls[:3], "highest", 20)[0]
    assert highest["winner"] == "Alice"
    assert highest["winning_value"] == 900


def test_random_sets_support_ties_and_manual_split_without_deleting_rolls():
    rolls = [
        RandomEvent(at(0), "Alice", 0, 1000, 800),
        RandomEvent(at(1), "Bob", 0, 1000, 800),
        RandomEvent(at(2), "Cara", 0, 1000, 700),
    ]
    tied = build_random_sets(rolls, "first", 20)
    assert tied[0]["winner"] == "Alice / Bob"
    split = build_random_sets(rolls, "first", 20, {at(2)})
    assert len(split) == 2
    assert sum(values["rolls"] for values in split) == 3


def test_incoming_damage_and_avoidance_stay_with_the_opponent_fight():
    tracker = CombatTracker()
    tracker.ingest(at(0), "You slash a giant for 20 points of damage.")
    tracker.ingest(at(1), "a giant hits You for 15 points of damage.")
    tracker.ingest(at(2), "a giant tries to hit You, but misses!")

    fight = tracker.active["a giant"]
    assert fight.total_damage == 20
    assert fight.tanks["You"].damage == 15
    assert fight.tanks["You"].misses == 1
    assert [event.kind for event in fight.events] == [
        "Damage", "Incoming", "Avoided"]


def test_learns_pet_leader_and_can_merge_pet_damage_into_owner():
    tracker = CombatTracker()
    tracker.ingest(at(0), "Gabtik says, 'My leader is Alice.'")
    tracker.ingest(at(1), "Alice hits a bat for 10 points of damage.")
    tracker.ingest(at(2), "Gabtik hits a bat for 25 points of damage.")

    rows = tracker.pet_rows()
    assert rows[0]["pet"] == "Gabtik"
    assert rows[0]["owner"] == "Alice"
    merged = tracker.display_attackers(tracker.current(), True)
    assert len(merged) == 1
    assert merged[0].name == "Alice + pets"
    assert merged[0].damage == 35
    assert merged[0].source_names == {"Alice + pets", "Alice", "Gabtik"}


def test_tracks_tanking_hit_distribution_and_combat_timeline():
    tracker = CombatTracker()
    tracker.ingest(at(0), "a bat hits You for 7 points of damage.")
    tracker.ingest(at(1), "a bat hits You for 7 points of damage.")
    tracker.ingest(at(2), "a bat hits You for 9 points of damage.")
    stats = tracker.current().tanks["You"]
    assert stats.hit_counts == {7: 2, 9: 1}
    assert len(tracker.current().events) == 3


def test_gamparse_style_tanking_tracks_defense_order_and_attack_types():
    tracker = CombatTracker()
    tracker.ingest(at(0), "a giant slashes You for 12 points of damage.")
    tracker.ingest(at(1), "a giant tries to slash You, but You dodge!")
    tracker.ingest(at(2), "a giant tries to bash You, but You parry!")
    tracker.ingest(at(3), "a giant tries to hit You, but You riposte!")
    tracker.ingest(at(4), "a giant tries to crush You, but You block!")
    tracker.ingest(at(5), "a giant tries to kick You, but misses!")
    tracker.ingest(at(6), "a giant tries to hit You, but You are INVULNERABLE!")
    tracker.ingest(
        at(7), "a giant tries to hit You, but your magical skin absorbs the blow!")
    tracker.ingest(at(8), "Your opponent strikes through your defenses!")
    tracker.ingest(at(9), "a giant kicks You for 5 points of damage.")

    stats = tracker.current().tanks["You"]
    assert stats.attempts == 9
    assert (stats.hits, stats.real_hits, stats.absorbed) == (3, 2, 1)
    assert stats.invulnerable == 1
    assert stats.misses == 1
    assert (stats.dodges, stats.parries, stats.blocks, stats.ripostes) == (
        1, 1, 1, 1)
    assert stats.defended == 4
    assert stats.avoided == 4
    assert stats.strikethroughs == 1
    assert stats.accuracy == 75.0
    assert stats.defended_percent == 50.0
    assert stats.hit_counts == {12: 1, 5: 1}
    assert set(stats.by_type) == {
        "Slashing", "Bash", "Hit", "Crushing", "Kick"}
    assert stats.by_type["Slashing"].attempts == 2
    assert stats.by_type["Hit"].attempts == 3
    assert stats.by_type["Kick"].attempts == 2
    assert stats.defense_rates() == {
        "Invulnerable": (1, 9),
        "Missed": (1, 8),
        "Riposted": (1, 7),
        "Parried": (1, 6),
        "Dodged": (1, 5),
        "Blocked": (1, 4),
        "Defended": (4, 8),
        "Absorbed": (1, 3),
        "Hits": (2, 3),
    }
    assert stats.hit_count_rates() == {
        "Invulnerable": (1, 9),
        "Riposted": (1, 8),
        "Parried": (1, 7),
        "Dodged": (1, 6),
        "Blocked": (1, 5),
        "Defended": (4, 8),
        "Missed": (1, 4),
        "Hits": (3, 8),
        "Absorbed": (1, 3),
        "Real Hits": (2, 9),
    }
