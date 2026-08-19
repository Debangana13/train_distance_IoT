"""
services/mock_sensor.py — Realistic HC-SR04 sensor simulator.

Simulates six different physical scenarios to test the dashboard and AI
without requiring real Arduino hardware. The scenarios produce realistic
distance sequences that exercise every part of the AI risk engine.

Scenarios
---------
1. stable        : Object stationary ~100 cm, minor sensor noise
2. slow_approach : Object slowly moving toward sensor (100 → 40 cm)
3. rapid_approach: Object rapidly approaching (100 → 15 cm in ~10 s)
4. critical_event: Object already close and getting closer (40 → 10 cm)
5. noise         : Sensor noise around a stable baseline
6. random_demo   : Automatically cycles through all scenarios

Controls (accessible from the frontend in MOCK mode)
------------------------------------------------------
    set_scenario(name)          — switch active scenario
    set_speed_multiplier(x)     — speed up/slow down approach (0.1 – 3.0)
    set_starting_distance(d)    — reset starting position
    pause() / resume()          — halt/continue simulation
    reset()                     — restart current scenario from beginning
"""

import logging
import math
import random
import threading
import time

from services import analytics_service

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Simulator shared state (accessed from Flask routes too)
# ---------------------------------------------------------------------------

_state = {
    "scenario":          "random_demo",
    "speed_multiplier":  1.0,
    "starting_distance": 100.0,
    "paused":            False,
    "running":           False,
}
_state_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Public control API (called by POST /api/simulator/control)
# ---------------------------------------------------------------------------

def set_scenario(name: str):
    valid = ["stable", "slow_approach", "rapid_approach", "critical_event", "noise", "random_demo"]
    if name in valid:
        with _state_lock:
            _state["scenario"] = name
            _state["starting_distance"] = 100.0   # reset position on scenario change
        log.info("Simulator scenario → %s", name)


def set_speed_multiplier(value: float):
    with _state_lock:
        _state["speed_multiplier"] = max(0.1, min(5.0, float(value)))


def set_starting_distance(distance: float):
    with _state_lock:
        _state["starting_distance"] = max(5.0, min(300.0, float(distance)))


def pause():
    with _state_lock:
        _state["paused"] = True
    log.info("Simulator paused")


def resume():
    with _state_lock:
        _state["paused"] = False
    log.info("Simulator resumed")


def reset():
    with _state_lock:
        _state["starting_distance"] = 100.0
        _state["paused"] = False
    log.info("Simulator reset")


def get_state() -> dict:
    with _state_lock:
        return dict(_state)


# ---------------------------------------------------------------------------
# Scenario generators
# Each generator yields (distance, sleep_seconds) tuples indefinitely.
# ---------------------------------------------------------------------------

def _scenario_stable(start: float, speed: float):
    """Object stationary at ~start cm with minor sensor noise."""
    d = start
    while True:
        noise = random.gauss(0, 0.8)
        d = start + noise
        yield max(5.0, d), 1.0 / speed


def _scenario_slow_approach(start: float, speed: float):
    """Object slowly approaching from start to ~35 cm then resets."""
    d = start
    while True:
        step = random.uniform(1.5, 3.0) * speed
        d -= step
        noise = random.gauss(0, 0.6)
        d += noise
        if d < 35.0:
            d = start   # reset to start
        yield max(5.0, d), 1.0


def _scenario_rapid_approach(start: float, speed: float):
    """Object rapidly closing in from start to ~10 cm, then resets."""
    d = start
    while True:
        step = random.uniform(5.0, 10.0) * speed
        d -= step
        noise = random.gauss(0, 1.0)
        d += noise
        if d < 10.0:
            d = start
        yield max(5.0, d), 0.8


def _scenario_critical_event(start: float, speed: float):
    """Object already in caution zone, approaching critical threshold."""
    d = min(start, 45.0)   # start closer
    while True:
        step = random.uniform(2.0, 4.0) * speed
        d -= step
        noise = random.gauss(0, 0.5)
        d += noise
        if d < 5.0:
            d = 45.0   # reset after critical
        yield max(5.0, d), 0.9


def _scenario_noise(start: float, speed: float):
    """Sensor noise — random jumps around a stable mean."""
    base = start
    while True:
        d = base + random.gauss(0, 3.0) + random.choice([-1, 0, 0, 1]) * random.uniform(0, 2)
        yield max(5.0, d), 0.7


# ---------------------------------------------------------------------------
# Main simulation loop
# ---------------------------------------------------------------------------

_SCENARIO_GENERATORS = {
    "stable":         _scenario_stable,
    "slow_approach":  _scenario_slow_approach,
    "rapid_approach": _scenario_rapid_approach,
    "critical_event": _scenario_critical_event,
    "noise":          _scenario_noise,
}

_DEMO_CYCLE = ["stable", "slow_approach", "rapid_approach", "critical_event", "noise"]


def run():
    """
    Background thread entry point.

    Runs indefinitely, generating sensor readings according to the
    currently selected scenario and feeding them to analytics_service.
    """
    log.info("Mock sensor simulator started.")
    with _state_lock:
        _state["running"] = True

    demo_index = 0
    demo_step_count = 0
    DEMO_STEPS_PER_SCENARIO = 20   # readings per scenario in auto-demo

    active_scenario = None
    generator = None

    while True:
        # --- Read current control state ---
        with _state_lock:
            paused    = _state["paused"]
            scenario  = _state["scenario"]
            speed     = _state["speed_multiplier"]
            start_d   = _state["starting_distance"]

        if paused:
            time.sleep(0.2)
            continue

        # --- Determine which scenario to run ---
        if scenario == "random_demo":
            # Auto-cycle through all scenarios
            if demo_step_count >= DEMO_STEPS_PER_SCENARIO:
                demo_index = (demo_index + 1) % len(_DEMO_CYCLE)
                demo_step_count = 0
                active_scenario = None   # force generator reset

            effective_scenario = _DEMO_CYCLE[demo_index]
        else:
            effective_scenario = scenario

        # --- (Re)create the generator if scenario changed ---
        if active_scenario != effective_scenario:
            active_scenario = effective_scenario
            gen_fn = _SCENARIO_GENERATORS.get(effective_scenario, _scenario_stable)
            generator = gen_fn(start_d, speed)
            log.info("Simulator: running scenario '%s'", active_scenario)

        # --- Get next reading from generator ---
        try:
            distance, sleep_secs = next(generator)
        except StopIteration:
            generator = _SCENARIO_GENERATORS[active_scenario](start_d, speed)
            distance, sleep_secs = next(generator)

        # --- Feed into analytics pipeline ---
        analytics_service.process_reading(distance, sensor_mode="MOCK")
        demo_step_count += 1

        # --- Sleep (adjusted for speed multiplier) ---
        adjusted_sleep = sleep_secs / max(0.1, speed)
        time.sleep(max(0.1, adjusted_sleep))


def start_thread():
    """Launch the simulator in a daemon background thread."""
    t = threading.Thread(target=run, daemon=True, name="MockSensor")
    t.start()
    return t
