"""Decision cards: an instant template card, optionally rewritten by IBM Granite from masked facts only."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path

from explain.masker import assert_no_raw_ids, find_raw_ids

GRANITE_PATH = Path(os.environ.get("NYAYA_GRANITE_PATH", "/home/ibm-user/granite-4.0-h-350m-base-be.f16.gguf"))
GRANITE_TIMEOUT_S = float(os.environ.get("NYAYA_GRANITE_TIMEOUT", "4"))


def inr(x: float) -> str:
    """Indian digit grouping: 2500000 -> ₹25,00,000."""
    n = int(round(float(x)))
    s, neg = str(abs(n)), n < 0
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return ("-₹" if neg else "₹") + s


def template_card(f: dict) -> str:
    d = f["decision"]
    if d == "RELEASE":
        head = f"RELEASE: {inr(f['amount'])} paid in full."
    elif d == "REVIEW":
        head = (f"REVIEW: {inr(f['release_now'])} released now as a survival stipend; "
                f"{inr(f['escrow'])} held in escrow for up to {f['escrow_hours']} h.")
    else:
        head = f"HOLD: {inr(f['amount'])} blocked pending analyst review."
    ctx = f"{f['merchant_category']} payment at {f['hour']:02d}:00"
    if f["in_disaster_zone"]:
        ctx += f" inside a disaster zone (severity {f['severity_tier']})"
    unsure = " The model is unsure (its conformal set is not a single label)." if len(f["conformal_set"]) != 1 else ""
    reasons = "; ".join(f"{r['factor']} ({r['direction']})" for r in f["reasons"]) or "none"
    clause = f" Policy {f['clause_id']}: {f['clause_title']}." if f.get("clause_id") else ""
    cf = f" {f['counterfactual']}" if f.get("counterfactual") else ""
    return (f"{head} Context: {ctx}. Fraud probability {f['p_fraud']:.2f}, mule-ring score {f['p_mule']:.2f}."
            f"{unsure} Main factors: {reasons}.{clause}{cf}")


FEW_SHOT = [
    ({"decision": "RELEASE", "amount": 640, "merchant_category": "pharmacy", "hour": 2, "severity_tier": 4,
      "p_fraud": 0.08, "p_mule": 0.01, "clause_id": "3.1", "clause_title": "Displaced customers"},
     "The ₹640 pharmacy payment was released in full. It came from a disaster zone at night, which is expected "
     "for displaced families, and there is no sign of a mule ring (policy 3.1)."),
    ({"decision": "HOLD", "amount": 9000, "merchant_category": "p2p", "hour": 23, "severity_tier": 5,
      "p_fraud": 0.71, "p_mule": 0.93, "clause_id": "6.2", "clause_title": "Mule-ring override"},
     "The ₹9,000 transfer was held because the payee looks like part of a mule ring: it is collecting and "
     "forwarding many payments quickly (policy 6.2). An analyst will review it."),
]


def _shot(f: dict) -> str:
    keep = ("decision", "amount", "release_now", "escrow", "escrow_hours", "merchant_category", "hour",
            "severity_tier", "p_fraud", "p_mule", "clause_id", "clause_title")
    return json.dumps({k: f[k] for k in keep if k in f}, ensure_ascii=False)


def build_prompt(facts: dict) -> str:
    parts = ["Write one or two plain sentences explaining a payment decision to a bank customer. "
             "Use only the facts given.\n"]
    for f, out in FEW_SHOT:
        parts.append(f"Facts: {_shot(f)}\nExplanation: {out}\n")
    parts.append(f"Facts: {_shot(facts)}\nExplanation:")
    return "\n".join(parts)


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def check_output(text: str, facts: dict) -> tuple[bool, str]:
    """Reject anything that invents numbers, leaks IDs, or contradicts the decision."""
    if not (30 <= len(text) <= 450):
        return False, "length"
    if find_raw_ids(text):
        return False, "raw id"
    allowed = {str(v) for v in _numbers(facts)}
    for m in _NUM.findall(text):
        if m.replace(",", "") not in allowed:
            return False, f"number {m} not in facts"
    words = {"RELEASE": ("released", "paid"), "REVIEW": ("held", "escrow", "stipend"), "HOLD": ("held", "blocked")}
    if not any(w in text.lower() for w in words[facts["decision"]]):
        return False, "decision not stated"
    other = {"RELEASE": ("blocked",), "REVIEW": ("blocked",), "HOLD": ("paid in full", "released in full")}
    if any(w in text.lower() for w in other[facts["decision"]]):
        return False, "contradicts decision"
    return True, "ok"


def _numbers(facts: dict):
    yield "00"
    yield "0"
    for k in ("amount", "release_now", "escrow", "escrow_hours", "severity_tier", "hour"):
        v = facts.get(k)
        if v is not None:
            iv = int(v)
            yield iv
            yield f"{iv:02d}"
    for k in ("p_fraud", "p_mule"):
        v = facts.get(k)
        if v is not None:
            yield f"{v:.2f}"
            yield f"{v:.1f}"
    if facts.get("clause_id"):
        for part in re.findall(r"\d+(?:\.\d+)?", str(facts["clause_id"])):
            yield part
            yield from part.split(".")


class Granite:
    """Lazy llama.cpp wrapper. One generation at a time; callers get the template when it is busy or slow."""

    def __init__(self, path: Path = GRANITE_PATH, timeout_s: float = GRANITE_TIMEOUT_S):
        self.path = Path(path)
        self.timeout_s = timeout_s
        self._llm = None
        self._load_error: str | None = None
        self._busy = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="granite")

    @property
    def available(self) -> bool:
        return self.path.exists() and self._load_error is None

    def _load(self):
        if self._llm is None:
            from llama_cpp import Llama

            self._llm = Llama(model_path=str(self.path), n_ctx=1024,
                              n_threads=int(os.environ.get("NYAYA_GRANITE_THREADS", "2")), verbose=False)
        return self._llm

    def _generate(self, prompt: str) -> str:
        try:
            llm = self._load()
            out = llm(prompt, max_tokens=90, temperature=0.2, top_p=0.9, stop=["\n", "Facts:"])
            return out["choices"][0]["text"].strip()
        finally:
            self._busy.release()

    def rewrite(self, facts: dict) -> dict:
        """Returns {"card", "source": "granite"|"template", "reason", "prompt", "ms"}."""
        assert_no_raw_ids(json.dumps(facts, ensure_ascii=False))
        template = template_card(facts)
        prompt = build_prompt(facts)
        res = {"card": template, "source": "template", "prompt": prompt, "ms": 0.0}
        if not self.available:
            res["reason"] = self._load_error or "granite model file not found"
            return res
        if not self._busy.acquire(blocking=False):
            res["reason"] = "granite busy"
            return res
        t = time.perf_counter()
        fut = self._pool.submit(self._generate, prompt)
        try:
            text = fut.result(timeout=self.timeout_s)
        except FutureTimeout:
            res["reason"] = f"timeout after {self.timeout_s}s"
            return res
        except Exception as e:  # model failed to load or run: keep serving templates
            self._load_error = f"{type(e).__name__}: {e}"
            res["reason"] = self._load_error
            return res
        finally:
            res["ms"] = round((time.perf_counter() - t) * 1000, 1)
        ok, why = check_output(text, facts)
        res["raw_output"] = text
        if ok:
            res.update(card=text, source="granite", reason="passed check")
        else:
            res["reason"] = f"rejected: {why}"
        return res
