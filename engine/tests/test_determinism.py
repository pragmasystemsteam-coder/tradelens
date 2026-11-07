"""Two runs in separate processes with different hash seeds and time zones (DD 7.3)."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent

SCRIPT = """
import hashlib, json, sys
sys.path.insert(0, sys.argv[1])
from builders import synthetic
from conftest import R1_CONSTANTS, R1_USER
from tradelens_engine.run import run
from tradelens_engine.settings import Settings
cfg = Settings.from_json({"user": dict(R1_USER), "constants": R1_CONSTANTS})
res = run(synthetic(1500), cfg, instrument="XAU_USD", timeframe="1h", rule_version="r1.0")
blob = json.dumps({"events": [e.to_json() for e in res.events],
                   "zones": [z.to_json() for z in res.zones],
                   "state": res.state.to_json(), "hash": cfg.hash("r1.0")}, sort_keys=True)
print(hashlib.sha256(blob.encode()).hexdigest(), len(res.events))
"""


def run_in_process(seed: str, tz: str) -> str:
    env = {**os.environ, "PYTHONHASHSEED": seed, "TZ": tz}
    out = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-c", SCRIPT, str(TESTS)],
        capture_output=True, text=True, check=True, env=env,
    )  # fmt: skip
    return out.stdout.strip()


def test_determinism_two_processes():
    a = run_in_process("1", "UTC")
    b = run_in_process("4242", "Asia/Kolkata")
    assert a == b
    digest, count = a.split()
    assert len(digest) == 64
    assert int(count) > 0
    assert hashlib.sha256(b"x").hexdigest() != digest
