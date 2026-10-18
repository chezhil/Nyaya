"""NYAYA HTTP API.

    uvicorn api.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from api.service import Nyaya

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "dashboard"
ANALYST_TOKEN = os.environ.get("NYAYA_ANALYST_TOKEN")

svc: Nyaya | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global svc
    if svc is None:
        svc = Nyaya()
    yield


app = FastAPI(title="NYAYA", version="0.1", lifespan=lifespan,
              description="Disaster-aware fraud decisions on IBM LinuxONE")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])


def service() -> Nyaya:
    if svc is None:
        raise HTTPException(503, "starting")
    return svc


def analyst(x_analyst_token: Optional[str] = Header(default=None)):
    if ANALYST_TOKEN and x_analyst_token != ANALYST_TOKEN:
        raise HTTPException(401, "analyst token required")


class RecipientOverride(BaseModel):
    account_age_days: Optional[float] = None
    device_reuse_density: Optional[float] = None
    shared_subnet_count: Optional[float] = None


class Payment(BaseModel):
    """Payment columns from data/schema.md. Only sender_id, recipient_id and amount are required."""
    model_config = ConfigDict(extra="ignore")
    sender_id: str = Field(max_length=64)
    recipient_id: str = Field(max_length=64)
    amount: float = Field(gt=0, le=1e9)
    tx_id: Optional[str] = Field(default=None, max_length=64)
    ts: Optional[float | str] = None
    type: Optional[Literal["PAYMENT", "TRANSFER", "CASH_OUT", "DEBIT", "CASH_IN"]] = None
    oldbalanceOrg: Optional[float] = None
    newbalanceOrig: Optional[float] = None
    oldbalanceDest: Optional[float] = None
    newbalanceDest: Optional[float] = None
    hour: Optional[int] = Field(default=None, ge=0, le=23)
    geo_shift_km: Optional[float] = Field(default=None, ge=0)
    new_device: Optional[int] = Field(default=None, ge=0, le=1)
    merchant_category: Optional[str] = Field(default=None, max_length=32)
    in_disaster_zone: Optional[int] = Field(default=None, ge=0, le=1)
    severity_tier: Optional[int] = Field(default=None, ge=0, le=5)
    urgency: Optional[float] = Field(default=None, ge=0, le=10)
    device_id: Optional[str] = Field(default=None, max_length=64)
    subnet: Optional[str] = Field(default=None, max_length=64)
    recipient: Optional[RecipientOverride] = None


class PolicyOverrides(BaseModel):
    """What-if overrides of api/policy_defaults.json (Policy Console). Bounded, and unknown keys are rejected,
    so a typo or a negative stipend fails loudly instead of producing a nonsense decision."""
    model_config = ConfigDict(extra="forbid")
    alpha: Optional[float] = Field(default=None, ge=0, le=5)
    beta: Optional[float] = Field(default=None, ge=0, le=1e6)
    tau: Optional[float] = Field(default=None, ge=0, le=1e9)
    tau_review: Optional[float] = Field(default=None, ge=0, le=1e9)
    theta_mule: Optional[float] = Field(default=None, ge=0, le=1)
    stipend_cap: Optional[float] = Field(default=None, ge=0, le=1e7)
    escrow_hours: Optional[float] = Field(default=None, gt=0, le=720)
    zone_hold_needs_mule: Optional[bool] = None


class EvaluateRequest(Payment):
    # Any policy override makes the call a what-if: decided and returned, but not recorded anywhere.
    policy: Optional[PolicyOverrides] = None


class Event(BaseModel):
    sender_id: str
    recipient_id: str
    amount: float = Field(gt=0)
    ts: Optional[float | str] = None


class QueueAction(BaseModel):
    action: Literal["approve", "deny"]
    analyst: str = Field(default="analyst", max_length=40)


class Appeal(BaseModel):
    note: str = Field(default="", max_length=500)


class ReplayRequest(BaseModel):
    per_hour: int = Field(default=50, ge=5, le=500)
    seed: int = 11
    variant: Literal["base", "smurf", "device_spoof", "slow_drip"] = "base"


v1 = "/api/v1"


@app.post(f"{v1}/evaluate")
def evaluate(req: EvaluateRequest, s: Nyaya = Depends(service)):
    body = req.model_dump(exclude={"policy"}, exclude_none=True)
    overrides = req.policy.model_dump(exclude_none=True) if req.policy else None
    try:
        return s.evaluate(body, overrides, dry_run=req.policy is not None)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post(f"{v1}/events")
def events(evts: list[Event], s: Nyaya = Depends(service)):
    if len(evts) > 20000:
        raise HTTPException(413, "max 20000 events per call")
    return s.ingest_events([e.model_dump(exclude_none=True) for e in evts])


@app.get(f"{v1}/explain/{{explain_id}}")
def explain(explain_id: str, s: Nyaya = Depends(service)):
    out = s.explain(explain_id)
    if out is None:
        raise HTTPException(404, "unknown explain_id")
    return out


@app.post(f"{v1}/appeal/{{explain_id}}")
def appeal(explain_id: str, body: Appeal = Appeal(), s: Nyaya = Depends(service)):
    out = s.appeal(explain_id, body.note)
    if out is None:
        raise HTTPException(404, "not in the queue (only REVIEW and HOLD decisions can be appealed)")
    return out


@app.get(f"{v1}/queue")
def queue(s: Nyaya = Depends(service)):
    return {"items": s.queue_list()}


@app.post(f"{v1}/queue/advance-clock", dependencies=[Depends(analyst)])
def advance_clock(hours: float = 48, s: Nyaya = Depends(service)):
    return s.advance_clock(hours)


@app.post(f"{v1}/queue/{{explain_id}}", dependencies=[Depends(analyst)])
def queue_action(explain_id: str, body: QueueAction, s: Nyaya = Depends(service)):
    try:
        out = s.queue_action(explain_id, body.action, body.analyst)
    except ValueError as e:
        raise HTTPException(409, str(e))
    if out is None:
        raise HTTPException(404, "unknown explain_id")
    return out


@app.get(f"{v1}/ledger/verify")
def ledger_verify(s: Nyaya = Depends(service)):
    return s.ledger.verify()


@app.get(f"{v1}/ledger/tail")
def ledger_tail(n: int = 20, s: Nyaya = Depends(service)):
    recs = list(s.ledger.records())[-max(1, min(n, 200)):]
    return {"records": [{k: v for k, v in r.items() if k != "escrow_enc"} | {"escrow_encrypted": bool(r["escrow_enc"])}
                        for r in recs]}


@app.get(f"{v1}/system")
def system(s: Nyaya = Depends(service)):
    return s.system()


@app.get(f"{v1}/policy")
def policy(s: Nyaya = Depends(service)):
    return s.policy


@app.get(f"{v1}/scenarios")
def scenarios(s: Nyaya = Depends(service)):
    return {"scenarios": s.scenarios()}


@app.post(f"{v1}/scenarios/{{n}}/run")
def run_scenario(n: int, s: Nyaya = Depends(service)):
    try:
        return s.run_scenario(n)
    except KeyError:
        raise HTTPException(404, "unknown scenario")


@app.post(f"{v1}/replay")
def replay(req: ReplayRequest = ReplayRequest(), s: Nyaya = Depends(service)):
    return s.replay(req.per_hour, req.seed, req.variant)


def _sim(name: str, params: dict, s: Nyaya):
    out = s.sim_hook(name, params)
    if out is None:
        raise HTTPException(503, f"sim.{name} not available yet (Kaustub's sim/ package or artifacts/sim/{name}.json)")
    return out


@app.post(f"{v1}/simulate")
def simulate(params: dict = {}, s: Nyaya = Depends(service)):
    return _sim("simulate", params, s)


@app.get(f"{v1}/pareto")
def pareto(s: Nyaya = Depends(service)):
    return _sim("pareto", {}, s)


@app.get(f"{v1}/redteam")
def redteam(s: Nyaya = Depends(service)):
    return _sim("redteam", {}, s)


@app.get("/health")
def health():
    return {"ok": svc is not None}


if DASHBOARD.is_dir():
    app.mount("/", StaticFiles(directory=DASHBOARD, html=True), name="dashboard")
else:
    @app.get("/")
    def root():
        return RedirectResponse("/docs")
