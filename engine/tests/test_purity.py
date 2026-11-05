"""The engine must stay pure: no I/O, clock, randomness, floats or backend imports (DD-5, AD-02)."""

import ast
from pathlib import Path

import tradelens_engine

PKG = Path(tradelens_engine.__file__).parent
FORBIDDEN_MODULES = {
    "random",
    "time",
    "os",
    "sys",
    "socket",
    "subprocess",
    "threading",
    "asyncio",
    "secrets",
    "uuid",
    "httpx",
    "requests",
    "sqlalchemy",
    "redis",
    "psycopg",
    "api",
    "worker",
    "adapters",
}
FORBIDDEN_ATTRS = {"now", "utcnow", "today", "fromtimestamp", "time"}


def sources():
    files = sorted(PKG.rglob("*.py"))
    assert files, "engine package has no modules"
    return [(f, ast.parse(f.read_text(encoding="utf-8"))) for f in files]


def test_engine_has_no_forbidden_imports():
    bad = []
    for path, tree in sources():
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            bad += [f"{path.name}: {n}" for n in names if n.split(".")[0] in FORBIDDEN_MODULES]
    assert bad == []


def test_engine_has_no_floats_or_clock():
    bad = []
    for path, tree in sources():
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                bad.append(f"{path.name}:{node.lineno} float literal")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "float"
            ):
                bad.append(f"{path.name}:{node.lineno} float()")
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                bad.append(f"{path.name}:{node.lineno} true division")
            elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
                bad.append(f"{path.name}:{node.lineno} .{node.attr}")
    assert bad == []
