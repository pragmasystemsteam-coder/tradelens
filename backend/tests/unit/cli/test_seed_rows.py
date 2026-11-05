import json
import shutil

import pytest

from tradelens.cli.seed import load_seed_rows
from tradelens_engine import Settings, settings_hash

FX = {"EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "AUD_USD", "USD_CAD", "NZD_USD"}
COMMODITIES = {"XAU_USD", "XAG_USD", "WTICO_USD", "BCO_USD"}


def test_seed_counts(config_dir):
    rows = load_seed_rows(config_dir)
    assert len(rows.calendars) == 2
    assert len(rows.instruments) == 11
    assert {i["code"] for i in rows.instruments} == FX | COMMODITIES
    assert len(rows.series_status) == 55
    assert len(rows.rule_versions) == 1
    assert {p["code"] for p in rows.presets} == {"default", "scalping", "intraday", "swing"}


def test_series_status_covers_every_instrument_and_timeframe(config_dir):
    rows = load_seed_rows(config_dir)
    pairs = {(s["instrument"], s["timeframe"]) for s in rows.series_status}
    assert pairs == {(i, tf) for i in FX | COMMODITIES for tf in ("5m", "15m", "1h", "4h", "1d")}


def test_asset_classes_and_calendars(config_dir):
    rows = load_seed_rows(config_dir)
    by_code = {i["code"]: i for i in rows.instruments}
    assert {by_code[c]["asset_class"] for c in FX} == {"forex"}
    assert (
        by_code["XAU_USD"]["asset_class"] == "metal"
        and by_code["BCO_USD"]["asset_class"] == "energy"
    )
    assert {by_code[c]["calendar_code"] for c in FX} == {"fx_24x5"}
    assert {by_code[c]["calendar_code"] for c in COMMODITIES} == {"metal_energy_break"}
    assert (by_code["EUR_USD"]["price_scale"], by_code["USD_JPY"]["price_scale"]) == (5, 3)


def test_rule_version_matches_design(config_dir):
    rv = load_seed_rows(config_dir).rule_versions[0]
    assert rv["version"] == "r1.0"
    settings = Settings.from_json(rv["settings"])
    assert rv["settings_hash"] == settings.hash("r1.0")
    assert rv["weights"]["scoring_version"] == "s1.0"
    assert rv["weights"]["q_permille"] + rv["weights"]["c_permille"] == 1000


def test_presets_valid_settings_and_hashes(config_dir):
    rows = load_seed_rows(config_dir)
    rv = rows.rule_versions[0]
    constants = rv["settings"]["constants"]
    for preset in rows.presets:
        Settings.from_json({"user": preset["settings"], "constants": constants})
        assert preset["settings_hash"] == settings_hash("r1.0", preset["settings"], constants)
        assert preset["rule_version"] == "r1.0"
    default = next(p for p in rows.presets if p["code"] == "default")
    assert default["settings_hash"] == rv["settings_hash"]
    swing = next(p for p in rows.presets if p["code"] == "swing")
    assert (swing["settings"]["internal_pivot"], swing["settings"]["external_pivot"]) == (5, 15)


def _copy_config(config_dir, tmp_path):
    target = tmp_path / "config"
    shutil.copytree(config_dir, target)
    return target


def test_instruments_pip_le_price_scale(config_dir, tmp_path):
    target = _copy_config(config_dir, tmp_path)
    path = target / "instruments.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["instruments"][0]["pip_scale"] = data["instruments"][0]["price_scale"] + 1
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="pip_scale"):
        load_seed_rows(target)


def test_instrument_with_unknown_calendar_rejected(config_dir, tmp_path):
    target = _copy_config(config_dir, tmp_path)
    path = target / "instruments.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["instruments"][0]["calendar_code"] = "nope"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="calendar"):
        load_seed_rows(target)


def test_plans_json_matches_cr003(config_dir):
    plans = json.loads((config_dir / "plans.json").read_text(encoding="utf-8"))
    by_code = {p["code"]: p for p in plans["plans"]}
    assert [p["code"] for p in plans["plans"] if p.get("is_default")] == ["free"]
    assert by_code["pro_monthly"]["prices"] == {
        "INR": {"amount_minor": 99900, "interval": "month"},
        "USD": {"amount_minor": 1999, "interval": "month"},
    }
    assert by_code["pro_annual"]["prices"]["INR"]["amount_minor"] == 999900
    assert by_code["pro_annual"]["prices"]["USD"]["amount_minor"] == 19900
    assert by_code["pro_annual_founder"]["prices"]["INR"]["amount_minor"] == 799900
    assert by_code["pro_annual_founder"]["prices"]["USD"]["amount_minor"] == 15900
    assert by_code["pro_annual_founder"]["founder_cap"] == 100
    assert by_code["pro_monthly"]["trial_days"] == 15
    assert plans["country_currency"] == {"IN": "INR", "*": "USD"}
    assert by_code["free"]["limits"]["chart_history_candles"] == 500
    assert plans["limit_sets"]["pro"]["chart_history_candles"] == 2000


def _break_instruments(target):
    path = target / "instruments.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["instruments"][0]["pip_scale"] = 9
    path.write_text(json.dumps(data), encoding="utf-8")


UNREACHABLE = "postgresql+psycopg://u:p@127.0.0.1:1/none"


def test_seed_main_requires_migration_url(monkeypatch, config_dir):
    from tradelens.cli.seed import main

    monkeypatch.delenv("DATABASE_MIGRATION_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE)  # the app role must never run the seed
    assert main([str(config_dir)]) == 1


def test_seed_main_returns_1_on_bad_config(monkeypatch, config_dir, tmp_path):
    from tradelens.cli.seed import main

    target = _copy_config(config_dir, tmp_path)
    _break_instruments(target)
    monkeypatch.setenv("DATABASE_MIGRATION_URL", UNREACHABLE)
    assert main([str(target)]) == 1


def test_seed_main_returns_1_when_database_unreachable(monkeypatch, config_dir):
    from tradelens.cli.seed import main

    monkeypatch.setenv("DATABASE_MIGRATION_URL", UNREACHABLE)
    assert main([str(config_dir)]) == 1


def test_rule_file_missing_key_is_config_error(config_dir, tmp_path):
    from tradelens.modules.analysis.public import RuleConfigError

    target = _copy_config(config_dir, tmp_path)
    path = target / "rules" / "r1.0.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["scoring_version"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RuleConfigError, match="scoring_version"):
        load_seed_rows(target)


def test_rule_weights_must_be_integers(config_dir, tmp_path):
    from tradelens.modules.analysis.public import RuleConfigError

    target = _copy_config(config_dir, tmp_path)
    path = target / "rules" / "r1.0.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["weights"]["high_quality"] = "60"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RuleConfigError, match="high_quality"):
        load_seed_rows(target)
