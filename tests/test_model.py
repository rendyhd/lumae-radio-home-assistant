"""What the radio's answers mean, without a radio."""

from __future__ import annotations

from custom_components.lumae_radio import model

DAY = model.DAY_MS


def status(
    state: str = "playing", track: bool = True, station: str | None = "stn"
) -> dict:
    return {
        "playback": {
            "state": state,
            "stationId": station,
            "track": {"id": "t1", "title": "Holocene", "artworkId": "t1"}
            if track
            else None,
            "positionMs": 64_000,
            "durationMs": 336_000,
            "selection": {"fit": 0.87, "priorRestMs": 3_600_000, "priorRadioPlays": 4},
        },
        "health": {
            "message": None,
            "continuity": "online",
            "maintenance": {"state": "idle"},
        },
        "volume": 0.62,
    }


def test_playback_projection() -> None:
    current = status()
    assert model.playback_state(current) == "playing"
    assert model.playback_state({"playback": {"state": "exploded"}}) == "stopped"
    assert model.position_seconds(current) == 64
    assert model.duration_seconds(current) == 336
    assert model.position_seconds(status(track=False)) is None
    assert model.volume({"volume": 1.4}) == 1.0
    assert model.selection(current) == {
        "fit": 0.87,
        "prior_rest_ms": 3_600_000,
        "prior_radio_plays": 4,
        "energy_target": None,
        "track_energy": None,
        "scarcity": None,
    }


def test_play_means_resume_start_or_nothing() -> None:
    assert model.main_command(status("paused")) == "resume"
    assert model.main_command(status("stopped")) == "play"
    assert model.main_command(status("fault")) == "play"
    assert model.main_command(status("stopped", station=None)) is None
    assert model.main_command(status("playing")) is None


def test_station_summaries() -> None:
    steady = {
        "id": "s1",
        "name": "Deep focus",
        "definition": {"energySchedule": {"mode": "steady", "steadyEnergy": 0.4}},
        "preparationStatus": "preparing",
        "vibe": {"status": "following"},
    }
    assert model.station_summary(steady) == {
        "id": "s1",
        "name": "Deep focus",
        "mode": "steady",
        "steady_energy": 0.4,
        "preparation": "preparing",
        "vibe": "following",
    }
    older = {"id": "s2", "name": "", "definition": {}, "prepared": True}
    assert model.station_summary(older)["preparation"] == "ready"
    assert model.station_summary(older)["name"] == "Untitled station"
    assert model.station_summaries([{"name": "no id"}, older]) == [
        model.station_summary(older)
    ]


def test_standing_from_feedback_and_bans() -> None:
    station = {
        "feedback": [
            {"trackId": "t1", "stationPreference": 1, "restUntilMs": 5_000},
            {"trackId": "t2", "stationPreference": 7},
        ],
        "bans": [{"trackId": "t3"}, "t4"],
    }
    assert model.standing(station, "t1") == {
        "preference": 1,
        "rest_until_ms": 5000,
        "banned": False,
    }
    assert model.standing(station, "t2")["preference"] == 0
    assert (
        model.standing(station, "t3")["banned"]
        and model.standing(station, "t4")["banned"]
    )
    assert model.standing(None, "t1") == {
        "preference": 0,
        "rest_until_ms": None,
        "banned": False,
    }


def test_rests_stay_within_a_minute_and_a_year() -> None:
    now = 1_000_000
    assert model.rest_until_ms(now) == now + 7 * DAY
    assert model.rest_until_ms(now, days=30) == now + 30 * DAY
    assert model.rest_until_ms(now, until_ms=now + 5) == now + 60_000
    assert model.rest_until_ms(now, days=999) == now + 365 * DAY


def test_steer_choices_map_to_radio_actions() -> None:
    assert model.STEER_ACTIONS["favor"] == "favour"
    assert model.STEER_ACTIONS["less"] == "avoid"
    assert model.STEER_ACTIONS["allow"] == "unban"
    assert set(model.STEER_ACTIONS.values()) == {
        "favour",
        "avoid",
        "neutral",
        "rest",
        "unrest",
        "ban",
        "unban",
    }


def test_refusals_never_show_a_code() -> None:
    assert model.refusal_text("station-not-found").startswith("This station is gone")
    assert "-" not in model.refusal_text("something-new")
