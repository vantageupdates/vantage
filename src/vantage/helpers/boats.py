"""P99 boat observations and deterministic arrival schedules.

The route constants and phase calculation mirror the observable behavior of
the MIT-licensed EQTool boat scheduler.  PigParse remains the remote source;
Vantage labels old observations instead of presenting a long extrapolation as
fresh fact.
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime


@dataclass(frozen=True)
class BoatRoute:
    boat_id: int
    boat_name: str
    start_point: str
    pretty_name: str
    announcement: str
    announcement_to_dock: int
    end_point: str
    trip_seconds: float
    color: str


@dataclass(frozen=True)
class BoatSchedule:
    route: BoatRoute
    last_seen: datetime.datetime
    remaining_seconds: int
    source: str
    stale: bool


BOAT_ROUTES = (
    BoatRoute(
        0, "Barrel Barge", "oasis", "Oasis arrival",
        "Rack Stonebelly shouts, 'Da Barrel Barge will be here soon soon!'",
        119, "timorous", 779.75, "#586F88"),
    BoatRoute(
        0, "Barrel Barge", "timorous", "TD from Oasis arrival",
        "", 510, "oasis", 778.75, "#586F88"),
    BoatRoute(
        1, "Bloated Belly", "overthere", "Overthere arrival",
        "Rack Stonebelly shouts, 'Da Bloated Belly be leaving da Overdere now!'",
        1975, "timorous", 2025.0, "#8C5F4F"),
    BoatRoute(
        2, "Maiden's Voyage", "butcher", "BB to FV Transfer arrival",
        "Glisse Bluesea shouts 'The Maiden's Voyage is now ready to be boarded. Please form an orderly line to the shuttles, and remember, no pushing!",
        0, "firiona", 1230.0, "#806C46"),
    BoatRoute(
        2, "Maiden's Voyage", "firiona", "FV Transfer to BB arrival",
        "Glisse Bluesea shouts 'The Maiden's Voyage has departed the outpost at Firiona Vie. Please be ready to board the shuttles shortly, if you desire to make the journey to Kunark.",
        771, "butcher", 1230.0, "#806C46"),
    BoatRoute(
        3, "NRo–Iceclad boat", "nro", "NRo arrival",
        "Frankel the Pirate says 'Thar she be mates. All aboard thats goin aboard!'",
        0, "iceclad", 519.0, "#76537D"),
    BoatRoute(
        3, "NRo–Iceclad boat", "iceclad", "Iceclad from NRo arrival",
        "", 307, "nro", 519.0, "#76537D"),
)


def _aware(value):
    if isinstance(value, str):
        try:
            value = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime.datetime):
        return None
    if value.tzinfo is None:
        value = value.astimezone()
    return value.astimezone(datetime.timezone.utc)


def route_for_announcement(text):
    value = str(text or "")
    return next((
        route for route in BOAT_ROUTES
        if route.announcement and value.startswith(route.announcement)), None)


def _phase_seconds(source_route, elapsed_seconds):
    elapsed = max(0, int(abs(elapsed_seconds)))
    if elapsed > source_route.trip_seconds:
        cycles = int(elapsed / source_route.trip_seconds)
        elapsed = int(elapsed - cycles * source_route.trip_seconds)
    return elapsed


def _remaining_seconds(target_route, phase_seconds):
    remaining = target_route.announcement_to_dock - phase_seconds
    if remaining <= 0:
        remaining = int(
            target_route.trip_seconds - phase_seconds +
            target_route.announcement_to_dock)
    return max(1, remaining)


def schedules_from_activities(activities, now=None, source="PigParse API"):
    """Resolve the latest observation for each boat into endpoint arrivals."""
    now = _aware(now or datetime.datetime.now(datetime.timezone.utc))
    latest = {}
    for raw in activities if isinstance(activities, (list, tuple)) else ():
        if not isinstance(raw, dict):
            continue
        try:
            boat_id = int(raw.get("boat"))
        except (TypeError, ValueError):
            continue
        start_point = str(raw.get("startPoint", "") or "").casefold()
        last_seen = _aware(raw.get("lastSeen"))
        route = next((
            candidate for candidate in BOAT_ROUTES
            if candidate.boat_id == boat_id and
            candidate.start_point == start_point), None)
        if route is None or last_seen is None:
            continue
        previous = latest.get(boat_id)
        if previous is None or last_seen > previous[1]:
            latest[boat_id] = (route, last_seen)

    schedules = []
    for boat_id, (source_route, last_seen) in latest.items():
        elapsed = max(0.0, (now - last_seen).total_seconds())
        phase = _phase_seconds(source_route, elapsed)
        stale = elapsed > source_route.trip_seconds * 3
        for target_route in BOAT_ROUTES:
            if target_route.boat_id != boat_id:
                continue
            schedules.append(BoatSchedule(
                target_route, last_seen,
                _remaining_seconds(target_route, phase), source, stale))
    route_order = {
        (route.boat_id, route.start_point): index
        for index, route in enumerate(BOAT_ROUTES)}
    return sorted(schedules, key=lambda value: route_order[
        (value.route.boat_id, value.route.start_point)])
