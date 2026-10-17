"""User notices in Tamil / Hindi / English. Texts are written by the team (docs/notices.json), never machine-translated."""
from __future__ import annotations

import json
import os
from pathlib import Path

from explain.card import inr

ROOT = Path(__file__).resolve().parent.parent
NOTICES_PATH = Path(os.environ.get("NYAYA_NOTICES_PATH", ROOT / "docs" / "notices.json"))
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "notices_fixture.json"
LANGS = ("en", "ta", "hi")


class Notices:
    def __init__(self, path: Path | None = None):
        path = path or (NOTICES_PATH if NOTICES_PATH.exists() else FIXTURE_PATH)
        self.source = "fixture" if path == FIXTURE_PATH else "docs"
        self.templates = json.loads(path.read_text(encoding="utf-8"))

    def render(self, decision: str, amount: float, release_now: float, escrow: float, hours: int) -> dict:
        slots = {"amount": inr(amount), "release_now": inr(release_now), "escrow": inr(escrow), "hours": hours}
        tpl = self.templates.get(decision, {})
        out = {lang: (tpl[lang].format(**slots) if tpl.get(lang) else None) for lang in LANGS}
        out["source"] = self.source
        return out
