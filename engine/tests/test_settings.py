import hashlib
import json

import pytest

from tradelens_engine.settings import ALLOWED_VALUES, Settings, SettingsError, settings_hash


def test_from_json_round_trip(settings_obj):
    obj = settings_obj()
    s = Settings.from_json(obj)
    assert s.external_pivot == 10 and s.internal_pivot is None and s.displacement == "normal"
    assert s.to_json() == obj


def test_allowed_values_match_design():
    assert ALLOWED_VALUES == {
        "internal_pivot": (None, 2, 3, 5),
        "external_pivot": (8, 10, 15, 20),
        "fvg_min_m": (0, 250, 500, 1000),
        "eq_tol_m": (50, 100, 200),
        "displacement": ("normal", "strong"),
        "zone_max_age": (50, 100, 200),
        "zone_max_retests": (1, 2, 3),
        "counter_trend": ("warn", "hide"),
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("external_pivot", 9),
        ("internal_pivot", 4),
        ("fvg_min_m", 100),
        ("eq_tol_m", 0),
        ("displacement", "huge"),
        ("zone_max_age", 150),
        ("zone_max_retests", 0),
        ("counter_trend", "show"),
    ],
)
def test_settings_rejects_unlisted_value(settings_obj, key, value):
    with pytest.raises(SettingsError, match=key):
        Settings.from_json(settings_obj(**{key: value}))


@pytest.mark.parametrize("value", [True, 3.0])
def test_settings_rejects_bool_and_float_even_if_equal(settings_obj, value):
    # True == 1 and 3.0 == 3 are both in the allowed list; types must still be exact.
    with pytest.raises(SettingsError, match="zone_max_retests"):
        Settings.from_json(settings_obj(zone_max_retests=value))


def test_settings_rejects_unknown_and_missing_keys(settings_obj):
    obj = settings_obj()
    obj["user"]["foo"] = 1
    with pytest.raises(SettingsError, match="foo"):
        Settings.from_json(obj)
    obj = settings_obj()
    del obj["user"]["eq_tol_m"]
    with pytest.raises(SettingsError, match="eq_tol_m"):
        Settings.from_json(obj)
    with pytest.raises(SettingsError):
        Settings.from_json({"user": settings_obj()["user"]})


def test_settings_rejects_float_in_constants(settings_obj):
    obj = settings_obj()
    obj["constants"] = {**obj["constants"], "displacement": {"normal": {"single_m": 1.5}}}
    with pytest.raises(SettingsError, match="float"):
        Settings.from_json(obj)


def test_internal_pivot_default_by_tf(settings_obj):
    default = Settings.from_json(settings_obj())
    assert [default.internal_pivot_for(tf) for tf in ("5m", "15m", "1h", "4h", "1d")] == [
        3,
        3,
        3,
        5,
        5,
    ]
    custom = Settings.from_json(settings_obj(internal_pivot=2))
    assert {custom.internal_pivot_for(tf) for tf in ("5m", "4h", "1d")} == {2}


def test_hash_matches_design_formula(settings_obj):
    obj = settings_obj()
    expected = hashlib.sha256(
        json.dumps(
            {"rule_version": "r1.0", "settings": obj["user"], "constants": obj["constants"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert settings_hash("r1.0", obj["user"], obj["constants"]) == expected
    assert Settings.from_json(obj).hash("r1.0") == expected
    assert len(expected) == 64


def test_hash_stable_across_key_order(settings_obj):
    obj = settings_obj()
    reversed_user = dict(reversed(list(obj["user"].items())))
    reversed_constants = dict(reversed(list(obj["constants"].items())))
    assert settings_hash("r1.0", reversed_user, reversed_constants) == settings_hash(
        "r1.0", obj["user"], obj["constants"]
    )


def test_hash_changes_with_rule_version_and_setting(settings_obj):
    base = Settings.from_json(settings_obj())
    assert base.hash("r1.0") != base.hash("r1.1")
    assert Settings.from_json(settings_obj(eq_tol_m=200)).hash("r1.0") != base.hash("r1.0")


def test_settings_rejects_misspelled_constant(settings_obj):
    obj = settings_obj()
    constants = dict(obj["constants"])
    constants["atr_perod"] = constants.pop("atr_period")
    obj["constants"] = constants
    with pytest.raises(SettingsError, match="atr_period"):
        Settings.from_json(obj)


def test_settings_rejects_bool_constant(settings_obj):
    obj = settings_obj()
    obj["constants"] = {**obj["constants"], "bos_buffer_m": True}
    with pytest.raises(SettingsError, match="bos_buffer_m"):
        Settings.from_json(obj)


def test_settings_rejects_bad_session_time(settings_obj):
    obj = settings_obj()
    sessions = {**obj["constants"]["sessions_ny"], "asian": ["19:00", "24:00"]}
    obj["constants"] = {**obj["constants"], "sessions_ny": sessions}
    with pytest.raises(SettingsError, match="sessions_ny"):
        Settings.from_json(obj)


def test_settings_rejects_incomplete_displacement_table(settings_obj):
    obj = settings_obj()
    obj["constants"] = {**obj["constants"], "displacement": {"normal": {"single_m": 1500}}}
    with pytest.raises(SettingsError, match="displacement"):
        Settings.from_json(obj)
