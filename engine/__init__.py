"""NYAYA decision engine: expected-harm policy and counterfactuals (CONTRACTS.md section 3).

Exports `decide`, `counterfactual` and `ENGINE_VERSION`. Pure Python, no model code: scores come in, a decision
comes out, so the API, the 10k suite and the Policy Console all run exactly the same policy.
"""
from engine.counterfactual import counterfactual
from engine.policy import ENGINE_VERSION, decide

__all__ = ["decide", "counterfactual", "ENGINE_VERSION"]
