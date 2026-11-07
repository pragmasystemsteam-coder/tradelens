"""verify-instruments against recorded Twelve Data symbol searches (task 1.3, CR-004)."""

import dataclasses
import json
from pathlib import Path

from tradelens.cli.verify_instruments import main, verify
from tradelens.modules.market_data.public import load_instrument_specs

REPO = Path(__file__).resolve().parents[4]
FIX = REPO / "backend" / "tests" / "fixtures" / "twelvedata"


def recorded(name):
    return json.loads((FIX / name).read_text())["data"]


def specs():
    return load_instrument_specs(REPO / "config")


def test_verify_offline_ok_for_repo_config():
    assert verify(specs()) == []


def test_verify_reports_missing_and_duplicate_symbol():
    s = specs()
    s[1] = dataclasses.replace(s[1], twelvedata_symbol=None)
    s[2] = dataclasses.replace(s[2], twelvedata_symbol="EUR/USD")
    problems = verify(s)
    assert any("GBP_USD: no provider_symbols" in p for p in problems)
    assert any("USD_JPY: symbol EUR/USD also used by EUR_USD" in p for p in problems)


def test_verify_reports_unknown_symbol_from_recorded_search():
    s = [x for x in specs() if x.code == "EUR_USD"]
    assert verify(s, lambda symbol: recorded("symbol_search_empty.json")) == [
        "EUR_USD: Twelve Data has no symbol EUR/USD"
    ]


def test_verify_ok_with_recorded_search():
    s = [x for x in specs() if x.code in ("EUR_USD", "XAU_USD")]
    answers = {
        "EUR/USD": recorded("symbol_search_eurusd.json"),
        "XAU/USD": recorded("symbol_search_xauusd.json"),
    }
    assert verify(s, answers.__getitem__) == []


def test_verify_reports_wrong_instrument_type():
    s = [x for x in specs() if x.code == "EUR_USD"]
    data = recorded("symbol_search_eurusd.json")
    data[0]["instrument_type"] = "Common Stock"
    assert "unexpected instrument type" in verify(s, lambda symbol: data)[0]


def test_main_offline_exit_codes(capsys, tmp_path):
    assert main([str(REPO / "config")]) == 0
    assert "11 instruments, 0 differences" in capsys.readouterr().out
    assert main([str(tmp_path)]) == 1


def test_main_live_without_key_fails(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # no deploy/.env here
    assert main([str(REPO / "config"), "--live"]) == 1
    assert "TWELVEDATA_API_KEY" in capsys.readouterr().err


def test_verify_accepts_live_commodity_types():
    # Labels seen live on 2026-11-07: metals are "Precious Metal", oil is "Energy Resource".
    s = [x for x in specs() if x.code in ("XAG_USD", "WTICO_USD", "BCO_USD")]
    oil = "Energy Resource"
    kinds = {"XAG/USD": "Precious Metal", "WTI/USD": oil, "XBR/USD": oil}
    assert verify(s, lambda symbol: [{"symbol": symbol, "instrument_type": kinds[symbol]}]) == []
