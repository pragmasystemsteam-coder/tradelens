"""Public interface of analysis for other modules and the CLI (ADR-0001 section 4)."""

from tradelens.modules.analysis.service import (
    RuleConfigError,
    RuleRows,
    build_rule_rows,
    save_rule_rows,
)

__all__ = ["RuleConfigError", "RuleRows", "build_rule_rows", "save_rule_rows"]
