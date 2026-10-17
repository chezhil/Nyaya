"""Online feature store: rolling 15-min recipient windows + the Mule Centrality worker.

Uses data/features.py, the same code that generated the training data.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from pathlib import Path

from data.features import (
    MCI_WINDOW_S,
    MODEL_B_FEATURES,
    UNKNOWN_ACCOUNT,
    RecipientWindow,
    compute_mci,
    static_account_features,
)

ACCOUNTS_PATH = Path(os.environ.get("NYAYA_ACCOUNTS", Path.home() / "shared" / "data" / "accounts_v1.csv.gz"))


class FeatureStore:
    def __init__(self, accounts_path: Path | None = ACCOUNTS_PATH, mci_interval_s: float = 5.0):
        self.window = RecipientWindow()
        self._edges: deque = deque()
        self._mci: dict[str, float] = {}
        self._lock = threading.RLock()
        self._dirty = False
        self.latest_ts = 0.0
        self.mci_interval_s = mci_interval_s
        self.mci_runs = 0
        self.mci_last_ms = 0.0
        self.static: dict[str, dict] = {}
        self.accounts_source = None
        if accounts_path and Path(accounts_path).exists():
            import pandas as pd

            self.static = static_account_features(pd.read_csv(accounts_path))
            self.accounts_source = str(accounts_path)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def ingest(self, ts: float, sender: str, recipient: str, amount: float) -> None:
        with self._lock:
            self.window.add(ts, sender, recipient, amount)
            self._edges.append((ts, sender, recipient, amount))
            self.latest_ts = max(self.latest_ts, ts)
            self._dirty = True

    def reset_account(self, account: str) -> None:
        """Forget an account's window and edges (lets a demo scenario be re-run from a clean state)."""
        with self._lock:
            self.window._incoming.pop(account, None)
            self._mci.pop(account, None)
            self._edges = deque(e for e in self._edges if account not in (e[1], e[2]))
            self._dirty = True

    def refresh_mci(self) -> None:
        t = time.perf_counter()
        with self._lock:
            while self._edges and self.latest_ts - self._edges[0][0] >= MCI_WINDOW_S:
                self._edges.popleft()
            edges = [(s, r, a) for _, s, r, a in self._edges]
            self._dirty = False
        scores = compute_mci(edges)
        with self._lock:
            self._mci = scores
            self.mci_runs += 1
            self.mci_last_ms = round((time.perf_counter() - t) * 1000, 2)

    def recipient_features(self, recipient: str, ts: float, overrides: dict | None = None) -> dict:
        with self._lock:
            f = self.window.features(recipient, ts)
            f.update(self.static.get(recipient, UNKNOWN_ACCOUNT))
            f["mci"] = self._mci.get(recipient, 0.0)
        for k, v in (overrides or {}).items():
            if k in MODEL_B_FEATURES and v is not None:
                f[k] = float(v)
        return {k: f[k] for k in MODEL_B_FEATURES}

    # ---- background worker ----
    def _run(self):
        while not self._stop.wait(self.mci_interval_s):
            if self._dirty:
                try:
                    self.refresh_mci()
                except Exception:  # keep the worker alive; the next tick retries
                    pass
            if self.mci_runs % 60 == 0:
                with self._lock:
                    self.window.gc(self.latest_ts)

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="mci-worker", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()

    def info(self) -> dict:
        return {"accounts_loaded": len(self.static), "accounts_source": self.accounts_source,
                "edges_in_window": len(self._edges), "mci_runs": self.mci_runs, "mci_last_ms": self.mci_last_ms,
                "mci_nodes": len(self._mci), "worker_alive": bool(self._thread and self._thread.is_alive())}
