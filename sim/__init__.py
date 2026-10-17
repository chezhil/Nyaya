"""Evaluation hooks consumed by :mod:`api.service`.

The hooks intentionally refuse to report results from ``StubBundle``.  Evaluation
numbers are only meaningful when the trained artifacts are loaded.
"""

from sim.evaluation import pareto, redteam, simulate

__all__ = ["simulate", "pareto", "redteam"]
