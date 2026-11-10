"""Setup scoring: Q, C, combined rank, re-evaluation and explanations (DD 3.6, 3.7; task 2.2).

Pure and integer-only like the rest of the engine; weights come from ``rule_versions.weights``.
"""

from tradelens_engine.scoring.explain import explain, sentences
from tradelens_engine.scoring.model import (
    Factor,
    Revision,
    ScoringConfig,
    ScoringConfigError,
    Setup,
)
from tradelens_engine.scoring.rank import combined, high_quality, score_candidate
from tradelens_engine.scoring.reevaluate import CONFIRM_TFS, reevaluate

__all__ = [
    "CONFIRM_TFS",
    "Factor",
    "Revision",
    "ScoringConfig",
    "ScoringConfigError",
    "Setup",
    "combined",
    "explain",
    "high_quality",
    "reevaluate",
    "score_candidate",
    "sentences",
]
