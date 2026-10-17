"""BM25 retrieval over the Relief Policy document, so every decision card cites a clause."""
from __future__ import annotations

import os
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = Path(os.environ.get("NYAYA_POLICY_PATH", ROOT / "docs" / "relief_policy.md"))
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "policy_fixture.md"

_HEADING = re.compile(r"^###\s+(\S+)\s+(.*)$")
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = set("the a an of to and or in on for is are be by with this that it as at from any if not".split())

# Words added to the query for each decision so the right part of the policy wins ties.
DECISION_TERMS = {
    "RELEASE": "release full payment disaster displaced victim emergency",
    "REVIEW": "review survival stipend escrow hold remaining 48 hours appeal uncertain",
    "HOLD": "hold block mule ring syndicate fraud suspected analyst",
}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


def parse_clauses(markdown: str) -> list[dict]:
    clauses, cur = [], None
    for line in markdown.splitlines():
        m = _HEADING.match(line.strip())
        if m:
            if cur:
                clauses.append(cur)
            cur = {"id": m.group(1).rstrip("."), "title": m.group(2).strip(" —-"), "lines": []}
        elif cur is not None and not line.startswith("#"):
            cur["lines"].append(line)
        elif line.startswith("## ") and cur:
            clauses.append(cur)
            cur = None
    if cur:
        clauses.append(cur)
    out = []
    for c in clauses:
        text = " ".join(l.strip() for l in c["lines"] if l.strip())
        if text:
            out.append({"id": c["id"], "title": c["title"], "text": text})
    return out


class PolicyIndex:
    def __init__(self, path: Path | None = None):
        path = path or (POLICY_PATH if POLICY_PATH.exists() else FIXTURE_PATH)
        self.path = path
        self.source = "fixture" if path == FIXTURE_PATH else "docs"
        self.clauses = parse_clauses(path.read_text(encoding="utf-8"))
        if not self.clauses:
            raise ValueError(f"no '### <id> <title>' clauses found in {path}")
        self.bm25 = BM25Okapi([tokenize(c["title"] + " " + c["text"]) for c in self.clauses])

    def query(self, text: str) -> dict:
        scores = self.bm25.get_scores(tokenize(text))
        i = int(scores.argmax())
        c = self.clauses[i]
        return {"id": c["id"], "title": c["title"], "text": c["text"], "score": round(float(scores[i]), 3),
                "source": self.source}

    def for_decision(self, decision: str, tx: dict, reason_labels: list[str], mule_flag: bool) -> dict:
        parts = [DECISION_TERMS.get(decision, ""), str(tx.get("merchant_category", ""))]
        if tx.get("in_disaster_zone"):
            parts.append(f"disaster zone severity {tx.get('severity_tier', 0)}")
        if mule_flag:
            parts.append("mule ring network forwarding")
        parts += reason_labels
        return self.query(" ".join(parts))
