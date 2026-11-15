"""``create-user`` and ``load-plans`` commands: argument and environment checks (no database)."""

import pytest

from tradelens.cli import __main__ as cli
from tradelens.cli import create_user, load_plans


def test_create_user_refuses_in_production(monkeypatch, capsys):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_MIGRATION_URL", "postgresql+psycopg://u:p@127.0.0.1:1/x")
    assert create_user.main(["demo@example.com", "customer", "pro_monthly"]) == 1
    assert "production" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "match"),
    [
        ([], "usage"),
        (["demo@example.com", "customer"], "usage"),
        (["not-an-email", "customer", "free"], "email"),
        (["demo@example.com", "owner", "free"], "role"),
    ],
)
def test_create_user_rejects_bad_arguments(monkeypatch, capsys, argv, match):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_MIGRATION_URL", "postgresql+psycopg://u:p@127.0.0.1:1/x")
    assert create_user.main(argv) == 1
    assert match in capsys.readouterr().err


def test_create_user_needs_database_url(monkeypatch, capsys):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("DATABASE_MIGRATION_URL", raising=False)
    assert create_user.main(["demo@example.com", "customer", "free"]) == 1
    assert "DATABASE_MIGRATION_URL" in capsys.readouterr().err


def test_password_hash_is_argon2id():
    hashed = create_user.hash_password("correct horse battery staple")
    assert hashed.startswith("$argon2id$")
    assert "correct horse" not in hashed


def test_load_plans_rejects_invalid_config_before_connecting(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_MIGRATION_URL", "postgresql+psycopg://u:p@127.0.0.1:1/x")
    (tmp_path / "plans.json").write_text('{"plans": [], "limit_sets": {}, "country_currency": {}}')
    assert load_plans.main([str(tmp_path)]) == 1
    assert "invalid" in capsys.readouterr().err


def test_cli_lists_new_commands(capsys):
    assert cli.main(["nope"]) == 2
    usage = capsys.readouterr().err
    assert "load-plans" in usage
    assert "create-user" in usage


@pytest.mark.parametrize("env", [None, "", "prod", "Production"])
def test_create_user_refuses_unless_app_env_is_development_or_staging(monkeypatch, capsys, env):
    # Fail closed: an unset or unknown APP_ENV is treated like production.
    if env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", env)
    monkeypatch.setenv("DATABASE_MIGRATION_URL", "postgresql+psycopg://u:p@127.0.0.1:1/x")
    assert create_user.main(["demo@example.com", "customer", "free"]) == 1
    assert "APP_ENV" in capsys.readouterr().err
