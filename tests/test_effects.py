from unittest.mock import patch

import pytest

from app.effects import EFFECT_PRESETS, LightState, run_effect


class MockController:
    def __init__(self, initial: LightState):
        self.initial = initial
        self.state_calls: list[dict] = []

    def get_state(self, light_id: int) -> LightState:
        return self.initial

    def set_state(self, light_id: int, **kwargs):
        self.state_calls.append(kwargs)


@pytest.fixture
def mock_sleep():
    with patch("app.effects.time.sleep") as m:
        yield m


def test_all_presets_run_and_restore(mock_sleep):
    snapshot = LightState(on=True, bri=180, xy=(0.4, 0.4), ct=None)
    for name in EFFECT_PRESETS:
        ctl = MockController(snapshot)
        run_effect(ctl, 1, name)
        last = ctl.state_calls[-1]
        # Last call must always be the restore
        assert last["on"] == snapshot.on
        assert last["bri"] == snapshot.bri
        assert last["xy"] == snapshot.xy
        assert last["alert"] == "none"


def test_restore_happens_after_exception(mock_sleep):
    snapshot = LightState(on=False, bri=100, xy=None, ct=300)

    class FailingController(MockController):
        def set_state(self, light_id, **kwargs):
            self.state_calls.append(kwargs)
            if kwargs.get("alert") == "lselect":
                raise RuntimeError("simulated bridge error")

    ctl = FailingController(snapshot)
    with pytest.raises(RuntimeError):
        run_effect(ctl, 1, "soft_breathe_white")
    # Restore call still happened
    assert ctl.state_calls[-1]["on"] is False
    assert ctl.state_calls[-1]["bri"] == 100


def test_unknown_effect_raises():
    snapshot = LightState(on=True, bri=200, xy=None, ct=300)
    ctl = MockController(snapshot)
    with pytest.raises(ValueError, match="Unknown effect"):
        run_effect(ctl, 1, "nonexistent_effect")
