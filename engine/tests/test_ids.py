import hashlib
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tradelens_engine.ids import event_id, level_id, make_id, setup_id, zone_id

T1 = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
T2 = T1 + timedelta(minutes=5)
H = "a" * 64


def sha32(joined: str) -> str:
    return hashlib.sha256(joined.encode()).hexdigest()[:32]


def test_event_id_field_order():
    joined = "EUR_USD|5m|bos|internal|bull|2026-11-02T10:00:00Z|2026-11-02T10:05:00Z|108535|" + H
    assert event_id("EUR_USD", "5m", "bos", "internal", "bull", T1, T2, 108535, H) == sha32(joined)


def test_event_id_null_fields_are_empty_strings():
    joined = "EUR_USD|5m|displacement||bull|2026-11-02T10:00:00Z|2026-11-02T10:05:00Z||" + H
    assert event_id("EUR_USD", "5m", "displacement", None, "bull", T1, T2, None, H) == sha32(joined)


def test_swapping_fields_changes_id():
    a = event_id("EUR_USD", "5m", "bos", "internal", "bull", T1, T2, 108535, H)
    b = event_id("EUR_USD", "5m", "bos", "internal", "bull", T2, T1, 108535, H)
    assert a != b and len(a) == 32


def test_zone_level_setup_ids():
    assert zone_id("ob", "XAU_USD", "1h", "bear", T1, 2034000, 2034560, H) == sha32(
        "ob|XAU_USD|1h|bear|2026-11-02T10:00:00Z|2034000|2034560|" + H
    )
    assert level_id("EUR_USD", "15m", "pdh", "buy", T1, 108600, H) == sha32(
        "EUR_USD|15m|pdh|buy|2026-11-02T10:00:00Z|108600|" + H
    )
    assert setup_id("EUR_USD", "1h", "intraday", "bull", "b" * 32, H) == sha32(
        "EUR_USD|1h|intraday|bull|" + "b" * 32 + "|" + H
    )


def test_make_id_converts_aware_times_to_utc():
    ny = datetime(2026, 11, 2, 5, 0, tzinfo=ZoneInfo("America/New_York"))  # EST, = 10:00Z
    assert make_id(ny) == make_id(T1) == sha32("2026-11-02T10:00:00Z")


def test_make_id_rejects_naive_datetime():
    with pytest.raises(ValueError):
        make_id(datetime(2026, 11, 2, 10, 0))


@pytest.mark.parametrize("bad", [1.5, True, b"x", object()])
def test_make_id_rejects_non_canonical_types(bad):
    with pytest.raises(ValueError):
        make_id("EUR_USD", bad)


def test_make_id_rejects_separator_in_text():
    with pytest.raises(ValueError):
        make_id("EUR|USD")
