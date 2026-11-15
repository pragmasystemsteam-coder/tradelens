"""Public interface of analysis for other modules, the worker and the CLI (ADR-0001 section 4)."""

from tradelens.modules.analysis.chart_data import SqlChartSource, chart_payload
from tradelens.modules.analysis.output_store import SqlAnalysisStore
from tradelens.modules.analysis.process import (
    AnalysisStore,
    CandleSource,
    CloseBatch,
    CloseProcessor,
)
from tradelens.modules.analysis.service import (
    ActiveRule,
    RuleConfigError,
    RuleRows,
    build_rule_rows,
    load_active_rule,
    official_settings,
    save_rule_rows,
)

__all__ = [
    "ActiveRule",
    "AnalysisStore",
    "CandleSource",
    "CloseBatch",
    "CloseProcessor",
    "RuleConfigError",
    "RuleRows",
    "SqlAnalysisStore",
    "SqlChartSource",
    "build_rule_rows",
    "chart_payload",
    "load_active_rule",
    "official_settings",
    "save_rule_rows",
]
