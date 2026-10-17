"""Explainer container: Granite card rewrites over HTTP, so the LLM's memory and CPU stay out of the API process.

    uvicorn explain.server:app --host 127.0.0.1 --port 8001
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from explain.card import Granite
from explain.masker import RawIdLeak

app = FastAPI(title="NYAYA explainer")
granite = Granite()


@app.get("/health")
def health():
    return {"ok": True, "granite_file": str(granite.path), "granite_available": granite.available}


@app.post("/card")
def card(facts: dict):
    try:
        return granite.rewrite(facts)
    except RawIdLeak as e:
        raise HTTPException(422, str(e))
