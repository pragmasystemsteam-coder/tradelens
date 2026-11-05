"""ADR-0001 section 4 boundaries.

Cross-module imports go through public.py; only analysis imports the engine.
"""

import ast
from pathlib import Path

import tradelens

PACKAGE_ROOT = Path(tradelens.__file__).parent
MODULES_DIR = PACKAGE_ROOT / "modules"


def imported_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names += [f"{node.module}.{alias.name}" for alias in node.names]
    return names


def module_files():
    return [(p.relative_to(MODULES_DIR).parts[0], p) for p in sorted(MODULES_DIR.rglob("*.py"))]


def cross_module_violations(owner: str, names: list[str]) -> list[str]:
    """Imports of another module that do not go through its public.py."""
    bad = []
    for name in names:
        parts = name.split(".")
        if parts[:2] != ["tradelens", "modules"] or len(parts) < 3 or parts[2] == owner:
            continue
        if len(parts) < 4 or parts[3] != "public":
            bad.append(name)
    return bad


def test_modules_exist():
    assert module_files(), "no modules found"


def test_cross_module_imports_go_through_public():
    bad = []
    for owner, path in module_files():
        found = cross_module_violations(owner, imported_names(path))
        bad += [f"{path.relative_to(PACKAGE_ROOT)}: {name}" for name in found]
    assert bad == []


def test_only_analysis_imports_the_engine():
    bad = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        rel = path.relative_to(PACKAGE_ROOT)
        if rel.parts[:2] == ("modules", "analysis"):
            continue
        bad += [
            f"{rel}: {n}" for n in imported_names(path) if n.split(".")[0] == "tradelens_engine"
        ]
    assert bad == []


def test_checker_flags_internal_import():
    assert cross_module_violations("scanner", ["tradelens.modules.analysis.repository.x"]) == [
        "tradelens.modules.analysis.repository.x"
    ]
    assert cross_module_violations("scanner", ["tradelens.modules.analysis.service"]) == [
        "tradelens.modules.analysis.service"
    ]
    assert cross_module_violations("scanner", ["tradelens.modules.analysis.public.build"]) == []
    assert cross_module_violations("analysis", ["tradelens.modules.analysis.repository.x"]) == []
