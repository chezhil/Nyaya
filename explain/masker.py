"""Build the only facts Granite (or a log) is allowed to see. Raw identifiers never leave this module."""
from __future__ import annotations

import json
import re

# Patterns that look like an identifier: account/device/tx ids (P0000001, M000123, T00000042, C12345678),
# IPv4 / subnets, phone-length digit runs, long hex strings (hashes, device fingerprints), UPI handles, emails.
RAW_ID_PATTERNS = [
    re.compile(r"\b[A-Z]{1,4}\d{4,}\b"),
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?\b"),
    re.compile(r"(?<![\d,.])\d{10,}(?![\d,.])"),
    re.compile(r"\b[0-9a-fA-F]{16,}\b"),
    re.compile(r"\b[\w.\-]+@[\w.\-]+\b"),
]

ALLOWED = {
    "decision", "amount", "release_now", "escrow", "escrow_hours", "severity_tier", "in_disaster_zone",
    "merchant_category", "hour", "p_fraud", "p_mule", "conformal_set", "reasons", "clause_id", "clause_title",
    "counterfactual",
}

FEATURE_LABELS = {
    "type_code": "payment type", "amount": "payment amount", "oldbalanceOrg": "balance before payment",
    "newbalanceOrig": "balance after payment", "oldbalanceDest": "payee balance before",
    "newbalanceDest": "payee balance after", "hour": "time of day", "is_night": "night-time payment",
    "geo_shift_km": "distance from usual location", "new_device": "new or borrowed phone",
    "merchant_code": "merchant type", "in_disaster_zone": "inside a declared disaster zone",
    "severity_tier": "disaster severity", "orig_balance_err": "balance mismatch (payer)",
    "dest_balance_err": "balance mismatch (payee)", "amount_to_balance": "amount compared with balance",
    "orig_drained": "account emptied by this payment", "fan_in_15m": "payee's incoming payments in 15 min",
    "unique_senders_15m": "distinct payers to payee in 15 min",
    "forward_within_10m_ratio": "payee forwards money within 10 min", "account_age_days": "payee account age",
    "device_reuse_density": "payee phone shared with other accounts",
    "shared_subnet_count": "payee network shared with other accounts", "mci": "mule-ring centrality",
}
_SAFE_CATEGORIES = {
    "p2p", "grocery", "pharmacy", "clinic", "fuel", "telecom", "electronics", "jewellery", "travel",
    "utilities", "cash_out", "donation",
}


class RawIdLeak(AssertionError):
    pass


def find_raw_ids(text: str) -> list[str]:
    hits = []
    for pat in RAW_ID_PATTERNS:
        hits += [m.group(0) for m in pat.finditer(text)]
    return hits


def assert_no_raw_ids(text: str) -> None:
    hits = find_raw_ids(text)
    if hits:
        raise RawIdLeak(f"raw identifiers in masked output: {hits[:5]}")


def mask_facts(result: dict, tx: dict, policy: dict | None = None) -> dict:
    """Allow-list projection of a decision into facts safe for the LLM, the ledger and logs."""
    clause = result.get("policy_clause") or {}
    cf = result.get("counterfactual") or None
    facts = {
        "decision": result["decision"],
        "amount": round(float(tx["amount"])),
        "release_now": round(float(result.get("release_now", 0))),
        "escrow": round(float(result.get("escrow", 0))),
        "escrow_hours": int((policy or {}).get("escrow_hours", 48)),
        "severity_tier": int(tx.get("severity_tier", 0)),
        "in_disaster_zone": int(tx.get("in_disaster_zone", 0)),
        "merchant_category": str(tx.get("merchant_category", "p2p")),
        "hour": int(tx.get("hour", 12)),
        "p_fraud": round(float(result["p_fraud"]), 2),
        "p_mule": round(float(result.get("p_mule", 0.0)), 2),
        "conformal_set": list(result.get("conformal_set", [])),
        "reasons": [
            {"factor": FEATURE_LABELS.get(r["feature"], r["feature"]),
             "direction": "raises risk" if r["contribution"] > 0 else "lowers risk"}
            for r in result.get("reasons", [])[:3]
        ],
        "clause_id": clause.get("id"),
        "clause_title": clause.get("title"),
        "counterfactual": cf.get("text") if isinstance(cf, dict) else None,
    }
    assert set(facts) <= ALLOWED
    if facts["merchant_category"] not in _SAFE_CATEGORIES:
        facts["merchant_category"] = "other"
    assert_no_raw_ids(json.dumps(facts, ensure_ascii=False))
    return facts
