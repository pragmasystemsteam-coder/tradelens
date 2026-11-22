"""Public interface of analysis for other modules, the worker and the CLI (ADR-0001 section 4)."""

from tradelens.modules.analysis.chart import (
    ACTIVE_ZONE_STATES,
    OfficialRule,
    Overlays,
    Preset,
    compute_overlays,
    decode_state,
    find_preset,
    htf_zones,
    official_rule,
    overlays_from_json,
    overlays_json,
    provisional_swings,
    series_setups,
    series_states,
    stored_overlays,
    trend_strip,
    window_overlays,
)
from tradelens.modules.analysis.chart_data import SqlChartSource, chart_payload
from tradelens.modules.analysis.instrument_view import instrument_analysis
from tradelens.modules.analysis.output_store import SqlAnalysisStore
from tradelens.modules.analysis.process import (
    AnalysisStore,
    CandleSource,
    CloseBatch,
    CloseProcessor,
)
from tradelens.modules.analysis.scanner_cache import (
    group_rows,
    load_scanner_rows,
    rank,
    scanner_row,
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
from tradelens.modules.analysis.setups import (
    InstrumentMeta,
    SetupChanges,
    SetupScorer,
    scorer_for,
)

__all__ = [
    "ACTIVE_ZONE_STATES",
    "ActiveRule",
    "AnalysisStore",
    "CandleSource",
    "CloseBatch",
    "CloseProcessor",
    "InstrumentMeta",
    "OfficialRule",
    "Overlays",
    "Preset",
    "RuleConfigError",
    "RuleRows",
    "SetupChanges",
    "SetupScorer",
    "SqlAnalysisStore",
    "SqlChartSource",
    "build_rule_rows",
    "chart_payload",
    "compute_overlays",
    "decode_state",
    "find_preset",
    "group_rows",
    "htf_zones",
    "instrument_analysis",
    "load_active_rule",
    "load_scanner_rows",
    "official_rule",
    "official_settings",
    "overlays_from_json",
    "overlays_json",
    "provisional_swings",
    "rank",
    "save_rule_rows",
    "scanner_row",
    "scorer_for",
    "series_setups",
    "series_states",
    "stored_overlays",
    "trend_strip",
    "window_overlays",
]
