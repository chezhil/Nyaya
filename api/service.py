"""NYAYA decision service: features -> models -> expected-harm engine -> explanation -> notice -> ledger.

Kept free of HTTP so tests, the load test and the dashboard all exercise the same code.
"""
from __future__ import annotations

import json
import os
import platform
import secrets
import sys
import threading
import time
import urllib.request
from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from api import fallback_policy
from api.bundle import ARTIFACTS, load_bundle
from api.feature_store import ACCOUNTS_PATH, FeatureStore
from data.features import tx_features
from explain.card import Granite, template_card
from explain.masker import FEATURE_LABELS, mask_facts
from explain.notices import Notices
from explain.policy import PolicyIndex
from ledger import Ledger

ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = Path(__file__).resolve().parent / "policy_defaults.json"
LEDGER_PATH = Path(os.environ.get("NYAYA_LEDGER", ROOT / "var" / "ledger.jsonl"))
SCENARIOS_PATH = ROOT / "data" / "scenarios" / "demo_scenarios.json"
IST = timezone(timedelta(hours=5, minutes=30))
MAX_EXPLAINS = 50_000
MAX_QUEUE = 20_000


def validate_policy(policy: dict) -> None:
    if "beta" in policy and float(policy["beta"]) <= 0:
        raise ValueError("beta must be positive")
    if "tau" in policy and float(policy["tau"]) <= 0:
        raise ValueError("tau must be positive")
    if "stipend_cap" in policy and float(policy["stipend_cap"]) < 0:
        raise ValueError("stipend_cap cannot be negative")
    if "alpha" in policy and float(policy["alpha"]) < 0:
        raise ValueError("alpha cannot be negative")
    if "theta_mule" in policy and not (0.0 < float(policy["theta_mule"]) <= 1.0):
        raise ValueError("theta_mule must be in (0, 1]")
    if "escrow_hours" in policy and float(policy["escrow_hours"]) <= 0:
        raise ValueError("escrow_hours must be positive")


def load_engine():
    """Kaustub's engine/ package if present (CONTRACTS.md §3), else the API fallback."""
    try:
        import engine  # type: ignore

        return engine.decide, getattr(engine, "counterfactual", None), getattr(engine, "ENGINE_VERSION", "engine")
    except ImportError:
        return fallback_policy.decide, None, fallback_policy.ENGINE_VERSION


def parse_ts(v) -> float:
    if v is None or v == "":
        return time.time()
    if isinstance(v, (int, float)):
        return float(v)
    return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()


class Nyaya:
    def __init__(self, artifacts: Path = ARTIFACTS, ledger_path: Path = LEDGER_PATH,
                 accounts_path: Path | None = ACCOUNTS_PATH, start_workers: bool = True,
                 ledger_key: bytes | None = None):
        self.started = time.time()
        self.bundle = load_bundle(artifacts)
        self.decide, self.counterfactual, self.engine_version = load_engine()
        self.policy = json.loads(POLICY_PATH.read_text())
        self.store = FeatureStore(accounts_path)
        self.ledger = Ledger(ledger_path, key=ledger_key)
        self.policy_index = PolicyIndex()
        self.notices = Notices()
        self.granite = Granite()
        self.explainer_url = os.environ.get("NYAYA_EXPLAINER_URL")
        self.explains: OrderedDict[str, dict] = OrderedDict()
        self.queue: dict[str, dict] = {}
        self.clock_offset = 0.0
        self.latencies: deque = deque(maxlen=5000)
        self._lock = threading.RLock()
        self._replay_cache: dict = {}
        self._stop = threading.Event()
        if start_workers:
            self.store.start()
            threading.Thread(target=self._escrow_loop, name="escrow", daemon=True).start()

    # ------------------------------------------------------------------ evaluate
    def prepare(self, req: dict) -> dict:
        tx = {k: v for k, v in req.items() if v is not None}
        if "sender_id" not in tx or not str(tx.get("sender_id", "")).strip():
            raise ValueError("sender_id is required")
        if "recipient_id" not in tx or not str(tx.get("recipient_id", "")).strip():
            raise ValueError("recipient_id is required")
        if "amount" not in tx:
            raise ValueError("amount is required")
        tx["amount"] = float(tx["amount"])
        if tx["amount"] <= 0:
            raise ValueError("amount must be positive")
        tx["ts"] = parse_ts(tx.get("ts"))
        if "hour" not in tx:
            tx["hour"] = datetime.fromtimestamp(tx["ts"], IST).hour
        tx.setdefault("type", "PAYMENT")
        tx.setdefault("merchant_category", "p2p")
        tx.setdefault("in_disaster_zone", 0)
        tx.setdefault("severity_tier", 0)
        if not tx["in_disaster_zone"]:
            tx["severity_tier"] = 0
        tx.setdefault("tx_id", "x" + secrets.token_hex(4))
        return tx

    def evaluate(self, req: dict, policy_overrides: dict | None = None) -> dict:
        t0 = time.perf_counter()
        tx = self.prepare(req)
        policy = {**self.policy, **(policy_overrides or {})}
        validate_policy(policy)

        self.store.ingest(tx["ts"], tx["sender_id"], tx["recipient_id"], tx["amount"])
        recip = self.store.recipient_features(tx["recipient_id"], tx["ts"], tx.get("recipient"))
        row = tx_features(tx)
        t1 = time.perf_counter()

        scores = self.bundle.score(row, recip)
        t2 = time.perf_counter()

        d = self.decide(scores, tx, policy)
        cf = None
        if self.counterfactual is not None:
            try:
                cf = self.counterfactual(row, lambda r: self.bundle.score(r, recip), policy, tx)
            except Exception as e:  # never fail a payment because the explanation failed
                cf = {"error": f"{type(e).__name__}: {e}"}
        t3 = time.perf_counter()

        mule_flag = scores["p_mule"] >= float(policy["theta_mule"])
        reasons = scores["contribs"]
        clause = self.policy_index.for_decision(
            d["decision"], tx, [FEATURE_LABELS.get(r["feature"], r["feature"]) for r in reasons], mule_flag)
        explain_id = "x" + secrets.token_hex(4)
        result = {
            "tx_id": tx["tx_id"], "decision": d["decision"], "release_now": d["release_now"],
            "escrow": d["escrow"], "p_fraud": scores["p_fraud"], "p_fraud_raw": scores.get("p_fraud_raw"),
            "p_mule": scores["p_mule"], "mule_flag": mule_flag, "conformal_set": scores["conformal_set"],
            "harm_delta": d["harm_delta"], "h_fraud": d.get("h_fraud"), "h_hold": d.get("h_hold"),
            "reasons": reasons, "counterfactual": cf, "policy_clause": clause,
        }
        facts = mask_facts(result, tx, policy)
        hours = int(policy["escrow_hours"])
        result["notice"] = self.notices.render(d["decision"], tx["amount"], d["release_now"], d["escrow"], hours)
        result["card_template"] = template_card(facts)
        result["explain_id"] = explain_id
        t4 = time.perf_counter()

        escrow = None
        if d["decision"] == "REVIEW":
            escrow = {"tx_id": tx["tx_id"], "sender_id": tx["sender_id"], "recipient_id": tx["recipient_id"],
                      "amount": tx["amount"], "escrow": d["escrow"],
                      "release_at": self.now() + hours * 3600}
        rec = self.ledger.append("decision", {
            "explain_id": explain_id, "facts": facts, "model_version": self.bundle.info()["model_version"],
            "engine_version": self.engine_version}, escrow=escrow)
        t5 = time.perf_counter()

        result.update({
            "ledger_hash": rec["hash"], "ledger_seq": rec["seq"],
            "latency_ms": round((t5 - t0) * 1000, 3),
            "latency_breakdown_ms": {"features": round((t1 - t0) * 1000, 3), "models": round((t2 - t1) * 1000, 3),
                                     "engine": round((t3 - t2) * 1000, 3), "explain": round((t4 - t3) * 1000, 3),
                                     "ledger": round((t5 - t4) * 1000, 3)},
            "model_version": self.bundle.info()["model_version"], "engine_version": self.engine_version,
            "mule_device": self.bundle.info()["mule_device"], "recipient_features": recip,
        })
        self.latencies.append(result["latency_ms"])
        with self._lock:
            self.explains[explain_id] = {"facts": facts, "result": result, "granite": None}
            while len(self.explains) > MAX_EXPLAINS:
                self.explains.popitem(last=False)
            if d["decision"] in ("REVIEW", "HOLD"):
                if len(self.queue) >= MAX_QUEUE:
                    completed = [k for k, v in self.queue.items() if v["status"] != "pending"]
                    for k in completed[:max(1, len(self.queue) - MAX_QUEUE + 1)]:
                        self.queue.pop(k, None)
                self.queue[explain_id] = {
                    "explain_id": explain_id, "tx_id": tx.get("tx_id"), "decision": d["decision"], "amount": tx["amount"],
                    "release_now": d["release_now"], "escrow": d["escrow"], "status": "pending",
                    "appealed": False, "created": self.now(), "ledger_seq": rec["seq"],
                    "release_at": escrow["release_at"] if escrow else None,
                    "p_fraud": scores["p_fraud"], "p_mule": scores["p_mule"], "mule_flag": mule_flag,
                    "merchant_category": facts["merchant_category"], "severity_tier": facts["severity_tier"],
                    "policy_clause": clause["id"],
                }
        return result

    def ingest_events(self, events: list[dict]) -> dict:
        for e in sorted(events, key=lambda e: parse_ts(e.get("ts"))):
            self.store.ingest(parse_ts(e.get("ts")), e["sender_id"], e["recipient_id"], float(e["amount"]))
        self.store.refresh_mci()
        return {"ingested": len(events), "feature_store": self.store.info()}

    # ------------------------------------------------------------------ explain
    def explain(self, explain_id: str) -> dict | None:
        with self._lock:
            item = self.explains.get(explain_id)
        if item is None:
            return None
        if item["granite"] is None:
            item["granite"] = self._granite(item["facts"])
        return {"explain_id": explain_id, "masked_facts": item["facts"],
                "card_template": item["result"]["card_template"], "granite": item["granite"],
                "policy_clause": item["result"]["policy_clause"], "reasons": item["result"]["reasons"],
                "counterfactual": item["result"]["counterfactual"]}

    def _granite(self, facts: dict) -> dict:
        if not self.explainer_url:
            return self.granite.rewrite(facts)
        try:
            req = urllib.request.Request(self.explainer_url.rstrip("/") + "/card", data=json.dumps(facts).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.granite.timeout_s + 2) as r:
                return json.load(r)
        except Exception as e:
            return {"card": template_card(facts), "source": "template", "reason": f"explainer unreachable: {e}"}

    # ------------------------------------------------------------------ queue / appeals / escrow
    def now(self) -> float:
        return time.time() + self.clock_offset

    def appeal(self, explain_id: str, note: str = "") -> dict | None:
        with self._lock:
            item = self.queue.get(explain_id)
            if item is None:
                item = next((v for v in self.queue.values() if v.get("tx_id") == explain_id), None)
            if item is None:
                return None
            item["appealed"] = True
            item["appealed_at"] = self.now()
            target_id = item["explain_id"]
        rec = self.ledger.append("appeal", {"explain_id": target_id, "note_chars": len(note)})
        return {**item, "ledger_hash": rec["hash"]}

    def queue_list(self) -> list[dict]:
        with self._lock:
            items = list(self.queue.values())
        return sorted(items, key=lambda i: (i["status"] != "pending", not i["appealed"], i["created"]))

    def queue_action(self, explain_id: str, action: str, analyst: str) -> dict | None:
        if action not in ("approve", "deny"):
            raise ValueError("action must be approve or deny")
        with self._lock:
            item = self.queue.get(explain_id)
            if item is None:
                item = next((v for v in self.queue.values() if v.get("tx_id") == explain_id), None)
            if item is None:
                return None
            if item["status"] != "pending":
                raise ValueError(f"already {item['status']}")
            item["status"] = "approved" if action == "approve" else "denied"
            item["decided_at"] = self.now()
            target_id = item["explain_id"]
        kind = "analyst_release" if action == "approve" else "analyst_fraud_confirmed"
        rec = self.ledger.append(kind, {"explain_id": target_id, "analyst": analyst[:40],
                                        "ledger_seq_decision": item["ledger_seq"]})
        return {**item, "ledger_hash": rec["hash"]}

    def adjudicate(self, explain_id: str, action: str, analyst: str = "analyst") -> dict | None:
        """Alias for queue_action to satisfy adjudication contract."""
        return self.queue_action(explain_id, action, analyst)

    def verify_ledger(self) -> dict:
        """Direct verification of the tamper-evident ledger hash chain."""
        return self.ledger.verify()

    def auto_release(self) -> list[str]:
        """Default-to-release: escrow goes to the customer after escrow_hours unless fraud was confirmed."""
        now, released = self.now(), []
        with self._lock:
            due = [i for i in self.queue.values()
                   if i["status"] == "pending" and i["release_at"] is not None and i["release_at"] <= now]
            for i in due:
                i["status"] = "auto_released"
                i["decided_at"] = now
        for i in due:
            self.ledger.append("escrow_auto_release", {"explain_id": i["explain_id"],
                                                       "ledger_seq_decision": i["ledger_seq"]})
            released.append(i["explain_id"])
        return released

    def advance_clock(self, hours: float) -> dict:
        """Demo control: move the escrow clock forward to show automatic release."""
        self.clock_offset += float(hours) * 3600
        return {"clock_offset_hours": self.clock_offset / 3600, "released": self.auto_release()}

    def _escrow_loop(self):
        while not self._stop.wait(30):
            try:
                self.auto_release()
            except Exception:
                pass

    # ------------------------------------------------------------------ scenarios / replay / sim
    def scenarios(self) -> list[dict]:
        return json.loads(SCENARIOS_PATH.read_text())["scenarios"]

    def run_scenario(self, n: int) -> dict:
        sc = next((s for s in self.scenarios() if s["n"] == n), None)
        if sc is None:
            raise KeyError(n)
        now = time.time()
        tx = {**sc["tx"], "ts": now}
        pre = sc.get("preload")
        if pre:
            rng = np.random.default_rng(n)
            r = tx["recipient_id"]
            self.store.reset_account(r)
            events, span = [], pre["minutes"] * 60
            for i in range(pre["burst"]):
                ts = now - span + i * span / pre["burst"]
                amt = float(round(rng.uniform(4000, 12000), 2))
                events.append({"ts": ts, "sender_id": f"S{n}{i:05d}", "recipient_id": r, "amount": amt})
                fwd = ts + float(rng.uniform(*pre["forward_delay_s"]))
                if fwd < now:
                    events.append({"ts": fwd, "sender_id": r, "recipient_id": pre["cashout_id"], "amount": amt * .97})
            self.ingest_events(events)
        result = self.evaluate(tx)
        return {"n": n, "name": sc["name"], "expected_by_design": sc["expected_by_design"],
                "notice_lang": sc.get("notice_lang", "en"), "preloaded_events": len(events) if pre else 0,
                "result": result}

    def replay(self, per_hour: int = 50, seed: int = 11, variant: str = "base") -> dict:
        from api.replay import run_replay

        key = (per_hour, seed, variant, self.bundle.info()["model_version"], self.engine_version,
               json.dumps(self.policy, sort_keys=True))
        if key not in self._replay_cache:
            self._replay_cache[key] = run_replay(self.bundle, self.decide, self.policy, per_hour, seed, variant)
        return self._replay_cache[key]

    def sim_ctx(self):
        return SimpleNamespace(bundle=self.bundle, decide=self.decide, policy=self.policy,
                               counterfactual=self.counterfactual)

    def sim_hook(self, name: str, params: dict) -> dict | None:
        try:
            import sim  # type: ignore

            fn = getattr(sim, name, None)
        except ImportError:
            fn = None
        if fn is not None:
            try:
                return fn(self.sim_ctx(), params)
            except (RuntimeError, FileNotFoundError):
                pass
        cached = Path(os.environ.get("NYAYA_ARTIFACTS", ARTIFACTS)) / "sim" / f"{name}.json"
        if cached.exists():
            return {**json.loads(cached.read_text()), "_source": str(cached.name)}
        return None

    # ------------------------------------------------------------------ system
    def system(self) -> dict:
        lat = np.array(self.latencies) if self.latencies else None
        return {
            "platform": platform_info(),
            "models": {**self.bundle.info(), "fallback_reason": getattr(self.bundle, "fallback_reason", None)},
            "engine_version": self.engine_version,
            "feature_store": self.store.info(),
            "ledger": {"records": len(self.ledger), "head": self.ledger.head, "path": str(self.ledger.path)},
            "explainer": {"granite_available": self.granite.available, "granite_path": str(self.granite.path),
                          "remote": self.explainer_url, "policy_source": self.policy_index.source,
                          "policy_clauses": len(self.policy_index.clauses), "notices_source": self.notices.source},
            "latency_ms": None if lat is None else {
                "n": int(lat.size), "p50": round(float(np.percentile(lat, 50)), 3),
                "p95": round(float(np.percentile(lat, 95)), 3), "p99": round(float(np.percentile(lat, 99)), 3)},
            "uptime_s": round(time.time() - self.started, 1),
            "queue_pending": sum(1 for i in self.queue.values() if i["status"] == "pending"),
        }


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def platform_info() -> dict:
    cpu = _read("/proc/cpuinfo") or ""
    features = set()
    for line in cpu.splitlines():
        if line.startswith("features"):
            features |= set(line.split(":", 1)[1].split())
    enforce = _read("/sys/fs/selinux/enforce")
    info = {
        "machine": platform.machine(), "byteorder": sys.byteorder, "python": platform.python_version(),
        "kernel": platform.release(), "cpu_features_nnpa": "nnpa" in features, "cpu_features_msa": "msa" in features,
        "selinux": {"1": "Enforcing", "0": "Permissive"}.get(enforce or "", "unavailable"),
        "uid": os.getuid() if hasattr(os, "getuid") else None,
        "in_container": Path("/run/.containerenv").exists() or Path("/.dockerenv").exists(),
    }
    try:
        import ssl

        info["openssl"] = ssl.OPENSSL_VERSION
    except Exception:
        pass
    try:
        import torch

        info["torch"] = torch.__version__
        info["torch_nnpa_available"] = bool(getattr(torch, "nnpa", None) and torch.nnpa.is_available())
    except Exception as e:
        info["torch"] = f"unavailable ({type(e).__name__})"
    return info
