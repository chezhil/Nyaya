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

_TAG = re.compile(r"\s*\((RELEASE|REVIEW|HOLD)\)\s*$")  # "(REVIEW)" at the end of a title: that decision only
_SUFFIXES = ("ments", "ment", "ings", "ing", "ions", "ion", "ed", "es", "s")

# What a decision rests on, and the words a clause TITLE must share to be cited for it. Matching titles (not the
# whole text) keeps a RELEASE off the REVIEW stipend clause and a HOLD without a mule flag off the mule override:
# those clauses mention release, victims and holds in passing. A basis no title matches gets no clause (id None)
# rather than a wrong one. BM25 over the clause text breaks ties between titles that match equally.
BASIS_TERMS = {
    "displaced": "displaced displacement victim",       # RELEASE inside a declared disaster zone
    "routine": "routine ordinary peacetime standard",   # RELEASE outside a zone
    "stipend": "review survival stipend",               # REVIEW
    "mule": "mule ring syndicate",                      # HOLD by the mule override
    "fraud": "clear fraud takeover block",              # HOLD by expected harm, no mule flag
}


def basis(decision: str, tx: dict, mule_flag: bool) -> str:
    if decision == "HOLD":
        return "mule" if mule_flag else "fraud"
    if decision == "REVIEW":
        return "stipend"
    return "displaced" if tx.get("in_disaster_zone") else "routine"


def _stem(t: str) -> str:
    """Crude suffix strip so 'displaced' and 'displacement' (or 'release' and 'released') match."""
    if len(t) > 4:
        for suf in _SUFFIXES:
            if t.endswith(suf) and len(t) - len(suf) >= 3:
                t = t[: -len(suf)]
                break
    return t[:-1] if len(t) > 3 and t.endswith("e") else t


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN.findall(text.lower()) if t not in _STOP]


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
        self._tags = [set(_TAG.findall(c["title"])) for c in self.clauses]
        self._titles = [set(tokenize(_TAG.sub("", c["title"]))) for c in self.clauses]

    def query(self, text: str) -> dict:
        scores = self.bm25.get_scores(tokenize(text))
        i = int(scores.argmax())
        c = self.clauses[i]
        return {"id": c["id"], "title": c["title"], "text": c["text"], "score": round(float(scores[i]), 3),
                "source": self.source}

    def for_decision(self, decision: str, tx: dict, reason_labels: list[str], mule_flag: bool) -> dict:
        b = basis(decision, tx, mule_flag)
        want = set(tokenize(BASIS_TERMS[b]))
        parts = [BASIS_TERMS[b], str(tx.get("merchant_category", ""))]
        if tx.get("in_disaster_zone"):
            parts.append(f"disaster zone severity {tx.get('severity_tier', 0)}")
        scores = self.bm25.get_scores(tokenize(" ".join(parts + reason_labels)))
        ok = [(len(self._titles[i] & want), float(scores[i]), i) for i in range(len(self.clauses))
              if self._titles[i] & want and (not self._tags[i] or decision in self._tags[i])]
        if not ok:
            return {"id": None, "title": None, "text": None, "score": 0.0, "source": self.source, "basis": b}
        _, score, i = max(ok)
        c = self.clauses[i]
        return {"id": c["id"], "title": c["title"], "text": c["text"], "score": round(score, 3),
                "source": self.source, "basis": b}
