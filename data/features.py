"""Feature definitions shared by the generator (offline) and the API feature store (online).

One implementation for both sides, so training and serving can't drift. See data/schema.md.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Iterable

import numpy as np

TX_TYPES = {"PAYMENT": 0, "TRANSFER": 1, "CASH_OUT": 2, "DEBIT": 3, "CASH_IN": 4}
MERCHANT_CATEGORIES = [
    "p2p", "grocery", "pharmacy", "clinic", "fuel", "telecom",
    "electronics", "jewellery", "travel", "utilities", "cash_out", "donation",
]
MERCHANT_CODES = {c: i for i, c in enumerate(MERCHANT_CATEGORIES)}

# Model A may use any subset of these (CONTRACTS.md §2).
MODEL_A_BASE = [
    "type_code", "amount", "oldbalanceOrg", "newbalanceOrig", "oldbalanceDest", "newbalanceDest",
    "hour", "is_night", "geo_shift_km", "new_device", "merchant_code", "in_disaster_zone", "severity_tier",
]
MODEL_A_DERIVED = ["orig_balance_err", "dest_balance_err", "amount_to_balance", "orig_drained"]
MODEL_A_FEATURES = MODEL_A_BASE + MODEL_A_DERIVED
# Features a "legacy" engine has no access to.
DISASTER_CONTEXT = ["in_disaster_zone", "severity_tier"]

MODEL_B_FEATURES = [
    "fan_in_15m", "unique_senders_15m", "forward_within_10m_ratio",
    "account_age_days", "device_reuse_density", "shared_subnet_count", "mci",
]

WINDOW_S = 15 * 60
FORWARD_S = 10 * 60
MCI_WINDOW_S = 60 * 60
MCI_SNAPSHOT_S = 5 * 60

# Used when the recipient is not in the accounts registry (a brand-new payee).
UNKNOWN_ACCOUNT = {"account_age_days": 0.0, "device_reuse_density": 0.0, "shared_subnet_count": 0.0}


def is_night(hour: int) -> int:
    return int(hour >= 22 or hour < 6)


def tx_features(tx: dict) -> dict:
    """Model A feature dict for one payment. Missing balance columns are derived as a clean ledger would."""
    amount = max(float(tx.get("amount", 0.0) or 0.0), 0.0)
    old_o = tx.get("oldbalanceOrg")
    old_o = amount if old_o is None else max(float(old_o), 0.0)
    new_o = tx.get("newbalanceOrig")
    new_o = max(old_o - amount, 0.0) if new_o is None else max(float(new_o), 0.0)
    old_d = tx.get("oldbalanceDest")
    old_d = 0.0 if old_d is None else max(float(old_d), 0.0)
    new_d = tx.get("newbalanceDest")
    new_d = old_d + amount if new_d is None else max(float(new_d), 0.0)
    hour = int(tx.get("hour", 12))
    return {
        "type_code": TX_TYPES.get(str(tx.get("type", "PAYMENT")).upper(), 0),
        "amount": amount,
        "oldbalanceOrg": old_o,
        "newbalanceOrig": new_o,
        "oldbalanceDest": old_d,
        "newbalanceDest": new_d,
        "hour": hour,
        "is_night": is_night(hour),
        "geo_shift_km": max(float(tx.get("geo_shift_km", 0.0) or 0.0), 0.0),
        "new_device": int(tx.get("new_device", 0) or 0),
        "merchant_code": MERCHANT_CODES.get(str(tx.get("merchant_category", "p2p")).lower(), 0),
        "in_disaster_zone": int(tx.get("in_disaster_zone", 0) or 0),
        "severity_tier": int(tx.get("severity_tier", 0) or 0),
        "orig_balance_err": old_o - amount - new_o,
        "dest_balance_err": old_d + amount - new_d,
        "amount_to_balance": amount / max(old_o + 1.0, 1e-4),
        "orig_drained": int(new_o <= 1.0 and old_o > 0),
    }


def tx_features_frame(df):
    """Vectorised tx_features over a DataFrame with the payment columns of data/schema.md."""
    import pandas as pd

    if df.empty:
        return pd.DataFrame(columns=MODEL_A_FEATURES)

    out = pd.DataFrame(index=df.index)
    if "type" in df.columns:
        out["type_code"] = df["type"].astype(str).str.upper().map(TX_TYPES).fillna(0).astype(int)
    else:
        out["type_code"] = 0

    amount = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0).clip(lower=0.0) if "amount" in df.columns else pd.Series(0.0, index=df.index)
    out["amount"] = amount

    if "oldbalanceOrg" in df.columns:
        old_o = pd.to_numeric(df["oldbalanceOrg"], errors="coerce").fillna(amount).clip(lower=0.0)
    else:
        old_o = amount.copy()
    out["oldbalanceOrg"] = old_o

    if "newbalanceOrig" in df.columns:
        new_o = pd.to_numeric(df["newbalanceOrig"], errors="coerce").fillna((old_o - amount).clip(lower=0.0)).clip(lower=0.0)
    else:
        new_o = (old_o - amount).clip(lower=0.0)
    out["newbalanceOrig"] = new_o

    if "oldbalanceDest" in df.columns:
        old_d = pd.to_numeric(df["oldbalanceDest"], errors="coerce").fillna(0.0).clip(lower=0.0)
    else:
        old_d = pd.Series(0.0, index=df.index)
    out["oldbalanceDest"] = old_d

    if "newbalanceDest" in df.columns:
        new_d = pd.to_numeric(df["newbalanceDest"], errors="coerce").fillna(old_d + amount).clip(lower=0.0)
    else:
        new_d = (old_d + amount).clip(lower=0.0)
    out["newbalanceDest"] = new_d

    out["hour"] = pd.to_numeric(df["hour"], errors="coerce").fillna(12).astype(int) if "hour" in df.columns else 12
    out["is_night"] = ((out["hour"] >= 22) | (out["hour"] < 6)).astype(int)
    out["geo_shift_km"] = pd.to_numeric(df["geo_shift_km"], errors="coerce").fillna(0.0).clip(lower=0.0) if "geo_shift_km" in df.columns else 0.0
    out["new_device"] = pd.to_numeric(df["new_device"], errors="coerce").fillna(0).astype(int) if "new_device" in df.columns else 0

    m_cat = df["merchant_category"].astype(str).str.lower() if "merchant_category" in df.columns else pd.Series("p2p", index=df.index)
    out["merchant_code"] = m_cat.map(MERCHANT_CODES).fillna(0).astype(int)

    out["in_disaster_zone"] = pd.to_numeric(df["in_disaster_zone"], errors="coerce").fillna(0).astype(int) if "in_disaster_zone" in df.columns else 0
    out["severity_tier"] = pd.to_numeric(df["severity_tier"], errors="coerce").fillna(0).astype(int) if "severity_tier" in df.columns else 0

    out["orig_balance_err"] = out["oldbalanceOrg"] - out["amount"] - out["newbalanceOrig"]
    out["dest_balance_err"] = out["oldbalanceDest"] + out["amount"] - out["newbalanceDest"]
    out["amount_to_balance"] = out["amount"] / (out["oldbalanceOrg"].clip(lower=0.0) + 1.0)
    out["orig_drained"] = ((out["newbalanceOrig"] <= 1.0) & (out["oldbalanceOrg"] > 0)).astype(int)
    return out[MODEL_A_FEATURES]


class RecipientWindow:
    """Rolling per-account windows of incoming payments.

    Convention: call add() for a payment *before* features() for its recipient, so fan_in counts the
    current payment. An incoming payment counts as "forwarded" once the recipient sends any payment within
    FORWARD_S after it; only payments seen so far are used (no look-ahead).
    """

    def __init__(self, window_s: int = WINDOW_S, forward_s: int = FORWARD_S):
        self.window_s = window_s
        self.forward_s = forward_s
        # account -> deque of [ts, sender, amount, forwarded]
        self._incoming: dict[str, deque] = defaultdict(deque)

    def add(self, ts: float, sender: str, recipient: str, amount: float) -> None:
        out_q = self._incoming.get(sender)
        if out_q:
            for item in reversed(out_q):
                delta = ts - item[0]
                if delta > self.forward_s:
                    break
                if delta >= 0:
                    item[3] = True
        self._incoming[recipient].append([ts, sender, amount, False])

    def _expire(self, account: str, now: float) -> deque:
        q = self._incoming.get(account)
        if q is None:
            return deque()
        while q and now - q[0][0] >= self.window_s:
            q.popleft()
        if any(now - item[0] >= self.window_s for item in q):
            q = deque(item for item in q if 0 <= now - item[0] < self.window_s)
            self._incoming[account] = q
        return q

    def features(self, recipient: str, now: float) -> dict:
        q = self._expire(recipient, now)
        n = len(q)
        if n == 0:
            return {"fan_in_15m": 0, "unique_senders_15m": 0, "forward_within_10m_ratio": 0.0}
        return {
            "fan_in_15m": n,
            "unique_senders_15m": len({item[1] for item in q}),
            "forward_within_10m_ratio": sum(1 for item in q if item[3]) / n,
        }

    def gc(self, now: float) -> None:
        for acct in list(self._incoming):
            if not self._expire(acct, now):
                del self._incoming[acct]


def compute_mci(edges: Iterable[tuple[str, str, float]]) -> dict[str, float]:
    """Mule Centrality Index over a transfer graph (data/schema.md §MCI).

    mci(r) = pagerank_percentile(r) * (0.5 + 0.5 * pass_through(r)) for nodes with in-degree >= 2, else 0.
    PageRank runs on the undirected weighted graph: directed PageRank favours money sinks (shops) over
    pass-through hubs, while undirected PageRank scores how central an account is in its transfer cluster.
    pass_through(r) = min(1, amount sent by r / amount received by r).
    """
    import networkx as nx

    g = nx.DiGraph()
    in_amt: dict[str, float] = defaultdict(float)
    out_amt: dict[str, float] = defaultdict(float)
    for s, r, a in edges:
        if g.has_edge(s, r):
            g[s][r]["weight"] += a
        else:
            g.add_edge(s, r, weight=a)
        in_amt[r] += a
        out_amt[s] += a
    if g.number_of_edges() == 0:
        return {}
    pr = nx.pagerank(g.to_undirected(), weight="weight", max_iter=200, tol=1e-6)
    receivers = [n for n in g.nodes if g.in_degree(n) >= 2]
    if not receivers:
        return {}
    vals = np.array([pr[n] for n in receivers])
    order = vals.argsort().argsort()
    pct = (order + 1) / len(receivers)
    out = {}
    for n, p in zip(receivers, pct):
        passthrough = min(1.0, out_amt.get(n, 0.0) / in_amt[n]) if in_amt[n] > 0 else 0.0
        out[n] = float(p * (0.5 + 0.5 * passthrough))
    return out


class MCITracker:
    """Keeps the last MCI_WINDOW_S of edges and recomputes MCI every MCI_SNAPSHOT_S of event time."""

    def __init__(self, window_s: int = MCI_WINDOW_S, snapshot_s: int = MCI_SNAPSHOT_S):
        self.window_s = window_s
        self.snapshot_s = snapshot_s
        self._edges: deque = deque()
        self._scores: dict[str, float] = {}
        self._next_snapshot: float | None = None
        self.snapshots = 0

    def add(self, ts: float, sender: str, recipient: str, amount: float) -> None:
        if self._next_snapshot is None:
            self._next_snapshot = (ts // self.snapshot_s + 1) * self.snapshot_s
        while ts >= self._next_snapshot:
            self.snapshot(self._next_snapshot)
            self._next_snapshot += self.snapshot_s
        self._edges.append((ts, sender, recipient, amount))

    def snapshot(self, now: float) -> None:
        while self._edges and now - self._edges[0][0] >= self.window_s:
            self._edges.popleft()
        self._scores = compute_mci((s, r, a) for t, s, r, a in self._edges if t <= now)
        self.snapshots += 1

    def get(self, account: str) -> float:
        return self._scores.get(account, 0.0)


def static_account_features(accounts) -> dict[str, dict]:
    """account_id -> {account_age_days, device_reuse_density, shared_subnet_count} from an accounts DataFrame."""
    dev_counts = accounts.groupby("device_id")["account_id"].transform("count") - 1
    net_counts = accounts.groupby("subnet")["account_id"].transform("count") - 1
    return {
        a: {"account_age_days": float(age), "device_reuse_density": float(d), "shared_subnet_count": float(n)}
        for a, age, d, n in zip(accounts["account_id"], accounts["account_age_days"], dev_counts, net_counts)
    }
