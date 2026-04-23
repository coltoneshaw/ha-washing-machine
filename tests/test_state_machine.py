"""State-machine tests for the washing machine coordinator."""
from __future__ import annotations

import pytest

from washing_machine import const as C


@pytest.mark.asyncio
async def test_idle_to_running(coord, hass, clock):
    """Power above start threshold for duration triggers RUNNING."""
    await coord.async_config_entry_first_refresh()
    assert coord.state == C.STATE_IDLE

    # Power crosses threshold
    hass.set_state("sensor.wm_power", "15.0")
    await coord.async_request_refresh()
    assert coord.state == C.STATE_IDLE  # not yet — needs sustained duration
    assert coord._state.pending_start_since is not None

    # Advance past start_duration
    clock.advance(seconds=31)
    await coord.async_request_refresh()
    assert coord.state == C.STATE_RUNNING
    assert coord._state.current_cycle_started is not None


@pytest.mark.asyncio
async def test_power_drop_resets_pending_start(coord, hass, clock):
    """If power drops back below threshold before duration, pending resets."""
    await coord.async_config_entry_first_refresh()
    hass.set_state("sensor.wm_power", "15.0")
    await coord.async_request_refresh()
    assert coord._state.pending_start_since is not None

    hass.set_state("sensor.wm_power", "1.0")
    await coord.async_request_refresh()
    assert coord._state.pending_start_since is None
    assert coord.state == C.STATE_IDLE


@pytest.mark.asyncio
async def test_running_to_done(coord, hass, clock):
    """Power below end threshold for end_duration triggers DONE + counter bump."""
    await coord.async_config_entry_first_refresh()
    # Force into RUNNING
    hass.set_state("sensor.wm_power", "15.0")
    await coord.async_request_refresh()
    clock.advance(seconds=31)
    await coord.async_request_refresh()
    assert coord.state == C.STATE_RUNNING
    baseline = coord.total_washes

    # Simulate a 45-minute cycle, then power drops
    clock.advance(minutes=45)
    hass.set_state("sensor.wm_power", "1.0")
    await coord.async_request_refresh()
    assert coord.state == C.STATE_RUNNING  # needs sustained low power

    # Sustain below for end_duration
    clock.advance(seconds=601)
    await coord.async_request_refresh()
    assert coord.state == C.STATE_DONE
    assert coord.total_washes == baseline + 1
    assert len(coord._state.cycle_history) == 1
    rec = coord._state.cycle_history[0]
    assert 40 <= rec["duration_min"] <= 56  # ~45 min + end duration wait


@pytest.mark.asyncio
async def test_spin_rest_does_not_false_finish(coord, hass, clock):
    """A brief low-power dip during spin rests does NOT trigger DONE."""
    await coord.async_config_entry_first_refresh()
    hass.set_state("sensor.wm_power", "15.0")
    await coord.async_request_refresh()
    clock.advance(seconds=31)
    await coord.async_request_refresh()
    assert coord.state == C.STATE_RUNNING

    # Dip below 2W for only 2 minutes, then back up (typical spin rest)
    clock.advance(minutes=10)
    hass.set_state("sensor.wm_power", "1.0")
    await coord.async_request_refresh()
    clock.advance(minutes=2)
    await coord.async_request_refresh()  # pending_end_since set
    hass.set_state("sensor.wm_power", "15.0")
    await coord.async_request_refresh()
    assert coord.state == C.STATE_RUNNING
    assert coord._state.pending_end_since is None


@pytest.mark.asyncio
async def test_done_to_idle_on_door_open(coord, hass, clock):
    """Door open after DONE records unload time and returns to IDLE."""
    await coord.async_config_entry_first_refresh()
    hass.set_state("sensor.wm_power", "15.0")
    await coord.async_request_refresh()
    clock.advance(seconds=31)
    await coord.async_request_refresh()
    clock.advance(minutes=45)
    hass.set_state("sensor.wm_power", "1.0")
    await coord.async_request_refresh()
    clock.advance(seconds=601)
    await coord.async_request_refresh()
    assert coord.state == C.STATE_DONE

    # Wait 15 minutes, open door
    clock.advance(minutes=15)
    hass.set_state("binary_sensor.wm_door", "on")
    await coord.async_request_refresh()
    assert coord.state == C.STATE_IDLE
    assert len(coord._state.unload_history) == 1
    assert 14 <= coord._state.unload_history[0]["unload_min"] <= 16


@pytest.mark.asyncio
async def test_error_on_long_cycle(coord, hass, clock):
    """Cycle running over error_duration_h transitions to ERROR."""
    await coord.async_config_entry_first_refresh()
    hass.set_state("sensor.wm_power", "15.0")
    await coord.async_request_refresh()
    clock.advance(seconds=31)
    await coord.async_request_refresh()
    assert coord.state == C.STATE_RUNNING

    clock.advance(hours=3, minutes=1)
    await coord.async_request_refresh()
    assert coord.state == C.STATE_ERROR


@pytest.mark.asyncio
async def test_outlier_unload_clamped(coord, hass, clock):
    """An unload time > 7 days is recorded as 0 (rejected)."""
    await coord.async_config_entry_first_refresh()
    # Manually put coordinator into DONE state 8 days ago
    hass.set_state("sensor.wm_power", "15.0")
    await coord.async_request_refresh()
    clock.advance(seconds=31)
    await coord.async_request_refresh()
    clock.advance(minutes=45)
    hass.set_state("sensor.wm_power", "1.0")
    await coord.async_request_refresh()
    clock.advance(seconds=601)
    await coord.async_request_refresh()
    assert coord.state == C.STATE_DONE

    clock.advance(days=8)
    hass.set_state("binary_sensor.wm_door", "on")
    await coord.async_request_refresh()
    # Outlier rejected — no unload record added
    assert coord._state.unload_history == []


@pytest.mark.asyncio
async def test_vacation_mode_suppresses_state(coord):
    """Vacation mode flips a flag; reminders logic gates on it at tick time."""
    await coord.async_config_entry_first_refresh()
    await coord.async_set_vacation_mode(True)
    assert coord.vacation_mode is True
    await coord.async_set_vacation_mode(False)
    assert coord.vacation_mode is False


@pytest.mark.asyncio
async def test_persistence_across_reload(hass, entry, clock):
    """Counters + history survive a coordinator reload via Store."""
    from washing_machine.coordinator import WashingMachineCoordinator
    from homeassistant.util import dt as dt_util

    # First instance: drive one full cycle
    c1 = WashingMachineCoordinator(hass, entry)
    await c1.async_load()
    hass.set_state("sensor.wm_power", "0")
    hass.set_state("binary_sensor.wm_door", "off")
    await c1.async_config_entry_first_refresh()
    hass.set_state("sensor.wm_power", "15.0")
    await c1.async_request_refresh()
    clock.advance(seconds=31)
    await c1.async_request_refresh()
    clock.advance(minutes=45)
    hass.set_state("sensor.wm_power", "1.0")
    await c1.async_request_refresh()
    clock.advance(seconds=601)
    await c1.async_request_refresh()
    assert c1.total_washes == 1
    assert len(c1._state.cycle_history) == 1
    await c1.async_shutdown()

    # Second instance: load should restore
    c2 = WashingMachineCoordinator(hass, entry)
    await c2.async_load()
    assert c2.total_washes == 1
    assert len(c2._state.cycle_history) == 1


@pytest.mark.asyncio
async def test_notifications_fired_on_transitions(coord, hass, clock):
    """Start + finish transitions invoke notify services."""
    await coord.async_config_entry_first_refresh()
    hass.services.async_call.reset_mock()

    hass.set_state("sensor.wm_power", "15.0")
    await coord.async_request_refresh()
    clock.advance(seconds=31)
    await coord.async_request_refresh()
    # Need to let async tasks run
    import asyncio
    await asyncio.sleep(0)
    # Should have called notify for "Started"
    assert hass.services.async_call.await_count >= 1
    # Validate domain + service parts of first call
    args = hass.services.async_call.await_args_list[0].args
    assert args[0] == "notify" and args[1] == "test"

    hass.services.async_call.reset_mock()
    clock.advance(minutes=45)
    hass.set_state("sensor.wm_power", "1.0")
    await coord.async_request_refresh()
    clock.advance(seconds=601)
    await coord.async_request_refresh()
    await asyncio.sleep(0)
    # Should have called notify for "Done!"
    assert hass.services.async_call.await_count >= 1


@pytest.mark.asyncio
async def test_reset_error(coord, hass, clock):
    """Manual reset from ERROR returns to IDLE."""
    await coord.async_config_entry_first_refresh()
    hass.set_state("sensor.wm_power", "15.0")
    await coord.async_request_refresh()
    clock.advance(seconds=31)
    await coord.async_request_refresh()
    clock.advance(hours=3, minutes=1)
    await coord.async_request_refresh()
    assert coord.state == C.STATE_ERROR
    await coord.async_reset_error()
    assert coord.state == C.STATE_IDLE


@pytest.mark.asyncio
async def test_counters_cannot_exceed_total(coord, hass, clock):
    """washes_today/week/month can never exceed total_washes (the old bug)."""
    from datetime import timezone
    await coord.async_config_entry_first_refresh()
    # Drive 3 cycles
    for _ in range(3):
        hass.set_state("sensor.wm_power", "15.0")
        await coord.async_request_refresh()
        clock.advance(seconds=31)
        await coord.async_request_refresh()
        clock.advance(minutes=45)
        hass.set_state("sensor.wm_power", "1.0")
        await coord.async_request_refresh()
        clock.advance(seconds=601)
        await coord.async_request_refresh()
        hass.set_state("binary_sensor.wm_door", "on")
        await coord.async_request_refresh()
        hass.set_state("binary_sensor.wm_door", "off")
        clock.advance(hours=1)

    assert coord.total_washes == 3
    # today should include all 3
    midnight_utc = clock.t.replace(hour=0, minute=0, second=0, microsecond=0)
    assert coord.washes_since(midnight_utc) == 3
    # Must never exceed total
    assert coord.washes_since(midnight_utc) <= coord.total_washes
