"""Counterfactuals: the smallest change among the top contributing features that improves the outcome.

Edits are made on the payment itself (not on a derived feature) and the Model A row is rebuilt with
`data.features.tx_features`, so the edited row stays internally consistent (an edited amount also moves
amount_to_balance, the balance error and the drained flag). The scoring function is the live one, so a
counterfactual is always something the real models and policy would actually do.
"""
from __future__ import annotations

from typing import Callable

from data.features import tx_features
from engine.policy import decide

ORDER = {"HOLD": 0, "REVIEW": 1, "RELEASE": 2}

# Model A feature -> the payment field a person could actually change.
AMOUNT_FEATURES = {"amount", "amount_to_balance", "orig_drained", "orig_balance_err", "newbalanceOrig",
                   "oldbalanceOrg", "dest_balance_err", "newbalanceDest", "oldbalanceDest"}
FIELD_OF = {"new_device": "new_device", "geo_shift_km": "geo_shift_km", "hour": "hour", "is_night": "hour",
            "severity_tier": "severity_tier", "in_disaster_zone": "severity_tier"}
AMOUNT_FACTORS = (0.75, 0.5, 0.25, 0.1)


def _candidates(field: str, tx: dict, policy: dict):
    """Yield (cost, new_tx_fields, description) from smallest to larger edits; cost is a relative change in [0, 1]."""
    if field == "amount":
        amount = max(0.0, float(tx.get("amount", 0.0) or 0.0))
        cap = float(policy.get("stipend_cap", 3000.0))
        if amount > 0:
            for f in AMOUNT_FACTORS:
                yield 1.0 - f, {"amount": round(amount * f, 2)}, f"the amount were Rs {amount * f:,.0f} instead of Rs {amount:,.0f}"
            if cap < amount:
                yield 1.0 - cap / amount, {"amount": cap}, f"the amount were Rs {cap:,.0f} (the survival stipend) instead of Rs {amount:,.0f}"
    elif field == "new_device" and int(tx.get("new_device") or 0):
        yield 0.5, {"new_device": 0}, "the payment came from your usual device"
    elif field == "geo_shift_km" and float(tx.get("geo_shift_km") or 0) > 0:
        km = float(tx.get("geo_shift_km") or 0)
        for f in (0.5, 0.25, 0.0):
            yield 1.0 - f, {"geo_shift_km": round(km * f, 1)}, f"the payment were made {km * f:,.0f} km from your usual location instead of {km:,.0f} km"
    elif field == "hour":
        hour = int(tx.get("hour") if tx.get("hour") is not None else 12)
        if hour >= 22 or hour < 6:
            yield 0.5, {"hour": 12}, "the payment were made in the daytime instead of at night"
    elif field == "severity_tier" and int(tx.get("severity_tier") or 0) > 0 and tx.get("in_disaster_zone"):
        s = min(5, int(tx["severity_tier"]))
        for new in range(s - 1, -1, -1):
            yield (s - new) / s, {"severity_tier": new, **({"in_disaster_zone": 0} if new == 0 else {})}, \
                f"the zone severity were {new} instead of {s}"


def _field_for(feature: str) -> str | None:
    if feature in AMOUNT_FEATURES:
        return "amount"
    return FIELD_OF.get(feature)


def counterfactual(row: dict, score_fn: Callable[[dict], dict], policy: dict, tx: dict) -> dict | None:
    """Smallest edit to one of the top-3 contributing features that improves the decision, or None.

    Prefers an edit that reaches RELEASE; otherwise the smallest edit that improves on the current outcome.
    """
    base_scores = score_fn(row)
    current = decide(base_scores, tx, policy)["decision"]
    if current == "RELEASE":
        return None

    fields: list[str] = []
    for c in (base_scores.get("contribs") or [])[:3]:
        f = _field_for(c.get("feature")) if isinstance(c, dict) else None
        if f and f not in fields:
            fields.append(f)

    base_feats = tx_features(tx)
    best_release, best_better = None, None
    for field in fields:
        for cost, edit, desc in _candidates(field, tx, policy):
            tx2 = {**tx, **edit}
            new_feats = tx_features(tx2)
            row2 = {**row, **{k: v for k, v in new_feats.items() if v != base_feats.get(k)}}
            new = decide(score_fn(row2), tx2, policy)["decision"]
            if ORDER[new] <= ORDER[current]:
                continue
            key = (round(cost, 4), field)
            hit = {"feature": field, "from": float(tx.get(field) or 0), "to": float(edit[field]),
                   "new_decision": new, "text": f"This would be {new} if {desc}."}
            if new == "RELEASE" and (best_release is None or key < best_release[0]):
                best_release = (key, hit)
            if best_better is None or key < best_better[0]:
                best_better = (key, hit)
    chosen = best_release or best_better
    return chosen[1] if chosen else None
