import pytest

R1_CONSTANTS = {
    "bos_buffer_m": 0,
    "sweep_window_bars": 20,
    "sweep_reclaim": "same_candle",
    "ob_lookback": 10,
    "disp_break_window": 3,
    "level_max_age": 300,
    "atr_period": 14,
    "body_ratio_permille": 650,
    "displacement": {
        "normal": {"single_m": 1500, "multi_m": 2000},
        "strong": {"single_m": 2000, "multi_m": 2500},
    },
    "sessions_ny": {
        "asian": ["19:00", "03:00"],
        "london": ["03:00", "12:00"],
        "new_york": ["08:00", "17:00"],
    },
}

R1_USER = {
    "internal_pivot": None,
    "external_pivot": 10,
    "fvg_min_m": 0,
    "eq_tol_m": 100,
    "displacement": "normal",
    "zone_max_age": 100,
    "zone_max_retests": 3,
    "counter_trend": "warn",
}


@pytest.fixture
def settings_obj():
    def make(**user_overrides):
        return {"user": {**R1_USER, **user_overrides}, "constants": R1_CONSTANTS}

    return make
