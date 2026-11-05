from tradelens.cli.doctor import REQUIRED_KEYS, check_env, parse_env, warnings_for


def example_env(repo):
    return parse_env((repo / "deploy" / ".env.example").read_text(encoding="utf-8"))


def filled_env(repo):
    env = {k: v.replace("change-me", "x" * 32) for k, v in example_env(repo).items()}
    env["RAZORPAY_KEY_ID_TEST"] = "rzp_test_abc123"
    return env


def test_every_required_key_is_in_example(repo):
    assert set(REQUIRED_KEYS) <= set(example_env(repo))


def test_example_env_with_placeholders_fails(repo):
    errors = check_env(example_env(repo))
    assert any("SESSION_SECRET" in e for e in errors)
    assert any("POSTGRES_PASSWORD" in e for e in errors)


def test_filled_env_passes(repo):
    assert check_env(filled_env(repo)) == []


def test_missing_required_key_fails(repo):
    env = filled_env(repo)
    del env["DATABASE_URL"]
    env["REDIS_URL"] = ""
    errors = check_env(env)
    assert any("DATABASE_URL" in e for e in errors)
    assert any("REDIS_URL" in e for e in errors)


def test_production_requires_cf_access(repo):
    env = filled_env(repo) | {"APP_ENV": "production", "CF_ACCESS_ENABLED": "false"}
    assert any("CF_ACCESS_ENABLED" in e for e in check_env(env))


def test_production_requires_api_docs_off(repo):
    env = filled_env(repo) | {"APP_ENV": "production", "ENABLE_API_DOCS": "true"}
    assert any("ENABLE_API_DOCS" in e for e in check_env(env))


def test_razorpay_key_prefix_must_match_mode(repo):
    env = filled_env(repo) | {"RAZORPAY_KEY_ID_TEST": "rzp_live_abc"}
    assert any("RAZORPAY_KEY_ID_TEST" in e for e in check_env(env))
    live = filled_env(repo) | {"RAZORPAY_MODE": "live", "RAZORPAY_KEY_ID_LIVE": ""}
    assert any("RAZORPAY_KEY_ID_LIVE" in e for e in check_env(live))


def test_production_warns_on_test_mode_and_practice(repo):
    env = filled_env(repo) | {"APP_ENV": "production"}
    found = warnings_for(env)
    assert any("RAZORPAY_MODE" in w for w in found)
    assert any("OANDA_ENV" in w for w in found)
    assert warnings_for(filled_env(repo)) == []


def test_parse_env_handles_comments_quotes_and_equals():
    env = parse_env('# c\nA=1\n\nB="two words"\nC=x=y\nexport D=4\n')
    assert env == {"A": "1", "B": "two words", "C": "x=y", "D": "4"}


def write_env(path, env):
    path.write_text("\n".join(f"{k}={v}" for k, v in env.items()), encoding="utf-8")
    return str(path)


def test_doctor_main_exit_codes(tmp_path, repo, monkeypatch):
    from tradelens.cli.doctor import main

    monkeypatch.setattr("tradelens.cli.doctor.docker_available", lambda: True)
    assert main([write_env(tmp_path / "good.env", filled_env(repo))]) == 0
    assert main([str(repo / "deploy" / ".env.example")]) == 1
    assert main([str(tmp_path / "missing.env")]) == 1


def test_doctor_fails_without_docker(tmp_path, repo, monkeypatch):
    from tradelens.cli.doctor import main

    monkeypatch.setattr("tradelens.cli.doctor.docker_available", lambda: False)
    assert main([write_env(tmp_path / "good.env", filled_env(repo))]) == 1
