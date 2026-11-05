from tradelens.core.config import AppConfig


def test_config_defaults_when_env_empty():
    cfg = AppConfig.from_env({})
    assert cfg.app_env == "development"
    assert (cfg.database_url, cfg.redis_url) == ("", "")
    assert cfg.enable_api_docs is False
    assert (cfg.heartbeat_interval_seconds, cfg.heartbeat_ttl_seconds) == (5, 15)


def test_config_reads_values():
    cfg = AppConfig.from_env(
        {"APP_ENV": "production", "ENABLE_API_DOCS": "TRUE", "HEARTBEAT_TTL_SECONDS": "20"}
    )
    assert cfg.app_env == "production" and cfg.enable_api_docs is True
    assert cfg.heartbeat_ttl_seconds == 20


def test_config_rejects_ttl_not_above_interval():
    import pytest

    with pytest.raises(ValueError, match="HEARTBEAT_TTL_SECONDS"):
        AppConfig.from_env({"HEARTBEAT_INTERVAL_SECONDS": "15", "HEARTBEAT_TTL_SECONDS": "15"})


def test_config_rejects_non_integer_value():
    import pytest

    with pytest.raises(ValueError, match="HEARTBEAT_TTL_SECONDS"):
        AppConfig.from_env({"HEARTBEAT_TTL_SECONDS": "abc"})
