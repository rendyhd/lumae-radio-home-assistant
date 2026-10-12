"""What the radio's status and stations mean, in the shapes Home Assistant shows.

Pure functions over the radio's JSON (headless/docs/API.md, Browser DTOs), kept apart from
Home Assistant so they are tested on their own. The words match the Lumae app's remote
(src/lib/radioRemoteView.ts).
"""

from __future__ import annotations

from typing import Any

PLAYBACK_STATES = frozenset({"playing", "paused", "stopped", "buffering", "fault"})

# The steer action's choices, and what each sends to the radio.
STEER_ACTIONS: dict[str, str] = {
    "favor": "favour",
    "less": "avoid",
    "no_preference": "neutral",
    "rest": "rest",
    "end_rest": "unrest",
    "ban": "ban",
    "allow": "unban",
}

DAY_MS = 86_400_000
MAX_REST_DAYS = 365


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def playback(status: dict[str, Any]) -> dict[str, Any]:
    return _dict(status.get("playback"))


def playback_state(status: dict[str, Any]) -> str:
    state = playback(status).get("state")
    return state if state in PLAYBACK_STATES else "stopped"


def track(status: dict[str, Any]) -> dict[str, Any] | None:
    value = playback(status).get("track")
    return value if isinstance(value, dict) and _text(value.get("id")) else None


def station_id(status: dict[str, Any]) -> str | None:
    return _text(playback(status).get("stationId"))


def volume(status: dict[str, Any]) -> float | None:
    level = _number(status.get("volume"))
    return None if level is None else min(1.0, max(0.0, level))


def position_seconds(status: dict[str, Any]) -> float | None:
    if track(status) is None:
        return None
    value = _number(playback(status).get("positionMs"))
    return None if value is None else max(0.0, value / 1000)


def duration_seconds(status: dict[str, Any]) -> float | None:
    if track(status) is None:
        return None
    value = _number(playback(status).get("durationMs"))
    return None if value is None or value <= 0 else value / 1000


def energy_mode(station: dict[str, Any]) -> str:
    schedule = _dict(_dict(station.get("definition")).get("energySchedule"))
    return "steady" if schedule.get("mode") == "steady" else "daily"


def station_summary(station: dict[str, Any]) -> dict[str, Any] | None:
    """One station for the station list: what the card and the source list need."""
    identifier = _text(station.get("id"))
    if identifier is None:
        return None
    schedule = _dict(_dict(station.get("definition")).get("energySchedule"))
    steady = _number(schedule.get("steadyEnergy"))
    status = station.get("preparationStatus")
    if status not in ("ready", "preparing", "failed", "needed"):
        status = "ready" if station.get("prepared") is True else "needed"
    vibe = _dict(station.get("vibe"))
    return {
        "id": identifier,
        "name": _text(station.get("name")) or "Untitled station",
        "mode": energy_mode(station),
        "steady_energy": steady if energy_mode(station) == "steady" else None,
        "preparation": status,
        "vibe": _text(vibe.get("status")),
    }


def station_summaries(stations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [summary for station in stations if (summary := station_summary(station))]


def find_station(
    stations: list[dict[str, Any]], identifier: str | None
) -> dict[str, Any] | None:
    if identifier is None:
        return None
    return next(
        (station for station in stations if station.get("id") == identifier), None
    )


def _ban_ids(station: dict[str, Any]) -> set[str]:
    bans: set[str] = set()
    for ban in station.get("bans") or []:
        if isinstance(ban, str):
            bans.add(ban)
        elif isinstance(ban, dict) and isinstance(ban.get("trackId"), str):
            bans.add(ban["trackId"])
    return bans


def standing(station: dict[str, Any] | None, track_id: str | None) -> dict[str, Any]:
    """How the station treats one track: its preference, rest and ban.

    From the station's first feedback page and its bans, as the Lumae app reads it.
    """
    if not station or not track_id:
        return {"preference": 0, "rest_until_ms": None, "banned": False}
    item = next(
        (
            entry
            for entry in station.get("feedback") or []
            if isinstance(entry, dict) and entry.get("trackId") == track_id
        ),
        {},
    )
    preference = item.get("stationPreference")
    rest = _number(item.get("restUntilMs"))
    return {
        "preference": preference if preference in (1, -1) else 0,
        "rest_until_ms": int(rest) if rest is not None else None,
        "banned": track_id in _ban_ids(station),
    }


def selection(status: dict[str, Any]) -> dict[str, Any] | None:
    """Why the radio chose this track: fit, earlier plays and energy (RadioSelectionExplanation)."""
    value = playback(status).get("selection")
    if not isinstance(value, dict):
        return None
    fit = _number(value.get("fit"))
    rest = _number(value.get("priorRestMs"))
    plays = _number(value.get("priorRadioPlays"))
    target = _number(value.get("energyTarget"))
    energy = _number(value.get("trackEnergy"))
    return {
        "fit": fit,
        "prior_rest_ms": int(rest) if rest is not None else None,
        "prior_radio_plays": int(plays) if plays is not None else None,
        "energy_target": target,
        "track_energy": energy,
        "scarcity": _text(value.get("scarcityTier")),
    }


def health(status: dict[str, Any]) -> dict[str, Any]:
    value = _dict(status.get("health"))
    maintenance = _dict(value.get("maintenance")).get("state")
    return {
        "fault": _text(value.get("message")),
        "continuity": _text(value.get("continuity")),
        "maintenance": maintenance if isinstance(maintenance, str) else None,
        "clock_trusted": value.get("clockTrusted")
        if isinstance(value.get("clockTrusted"), bool)
        else None,
        "auto_resume_suppressed": value.get("autoResumeSuppressed") is True,
    }


def rest_until_ms(
    now_ms: int, days: float | None = None, until_ms: int | None = None
) -> int:
    """A rest's end: `days` from now or an exact time, kept between a minute and 365 days."""
    target = until_ms if until_ms is not None else now_ms + round((days or 7) * DAY_MS)
    return int(min(now_ms + MAX_REST_DAYS * DAY_MS, max(now_ms + 60_000, target)))


# A refusal in plain words (the radio's web page and the Lumae app say the same); never the code.
REFUSALS: dict[str, str] = {
    "invalid-playback-state": "The radio was already doing that.",
    "no-active-queue": "Nothing is queued on the radio. Press play to start a station.",
    "skip-outcome-uncertain": "The radio couldn’t confirm the skip. Check what is playing.",
    "skip-outcome-uncertain-after-restart": "The radio couldn’t confirm the skip. Check what is playing.",
    "station-not-found": "This station is gone from the radio. Choose another.",
    "station-changed": "The station changed while the radio was working on it. It prepares the new version next.",
    "catalogue-not-ready": "The radio doesn’t have your library yet.",
    "preparation-not-ready": "This station is still being prepared.",
    "not-configured": "Connect the radio to your music server and AudioMuse-AI first.",
    "output-configuration-pending": "The radio is switching its sound output. Try again in a moment.",
    "output-start-failed": "The radio couldn’t start its sound. Check the speaker connection.",
    "feedback-operation-conflict": "The radio is still saving an earlier change to this track. Try again in a moment.",
    "feedback-cutover-unacknowledged": "The radio’s player didn’t confirm the change in time, so nothing changed. Try again.",
    "stale-feedback-revision": "This station’s track settings changed elsewhere. Try again.",
    "stale-device-revision": "Playback changed meanwhile. Try again.",
    "idempotency-conflict": "The radio changed meanwhile. Try again.",
    "invalid-feedback": "The radio didn’t accept that for this track.",
    "operation-busy": "The radio is busy with another job. Try again when it has finished.",
    "operation-limit": "The radio is busy. Try again in a moment.",
    "read-limit": "The radio is busy. Try again in a moment.",
    "service-shutdown": "The radio restarted before it finished. Try again.",
    "cancelled": "Canceled. The radio keeps what it had before.",
}


def refusal_text(code: str) -> str:
    return REFUSALS.get(code, "The radio couldn’t do that. Try again.")


def main_command(status: dict[str, Any]) -> str | None:
    """What Play means now: resume a pause, start the station, or nothing to start."""
    state = playback_state(status)
    if state in ("playing", "buffering"):
        return None
    if state == "paused":
        return "resume"
    return "play" if station_id(status) else None
