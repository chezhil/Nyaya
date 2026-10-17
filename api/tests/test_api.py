import json
import secrets

import pytest
from fastapi.testclient import TestClient

import api.main as main
from api import fallback_policy
from api.service import Nyaya
from explain.masker import find_raw_ids

POLICY = json.loads((main.ROOT / "api" / "policy_defaults.json").read_text())


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    d = tmp_path_factory.mktemp("nyaya")
    main.svc = Nyaya(artifacts=d / "no-artifacts", ledger_path=d / "ledger.jsonl", accounts_path=None,
                     start_workers=False, ledger_key=secrets.token_bytes(32))
    with TestClient(main.app) as c:
        yield c
    main.svc = None


MEENA = {"sender_id": "P9000001", "recipient_id": "M9000001", "type": "PAYMENT", "amount": 640,
         "oldbalanceOrg": 4200, "hour": 2, "geo_shift_km": 45, "new_device": 1, "merchant_category": "pharmacy",
         "in_disaster_zone": 1, "severity_tier": 4}


def test_evaluate_contract(client):
    r = client.post("/api/v1/evaluate", json=MEENA)
    assert r.status_code == 200, r.text
    body = r.json()
    for k in ("decision", "release_now", "escrow", "p_fraud", "p_mule", "conformal_set", "harm_delta", "reasons",
              "counterfactual", "policy_clause", "notice", "card_template", "explain_id", "ledger_hash",
              "latency_ms", "model_version", "engine_version"):
        assert k in body
    assert body["decision"] in ("RELEASE", "REVIEW", "HOLD")
    assert body["model_version"].startswith("stub")  # no artifacts in this test
    assert len(body["reasons"]) == 3 and len(body["ledger_hash"]) == 64
    assert body["release_now"] + body["escrow"] <= MEENA["amount"] + 1e-6


def test_validation(client):
    assert client.post("/api/v1/evaluate", json={**MEENA, "amount": -5}).status_code == 422
    assert client.post("/api/v1/evaluate", json={**MEENA, "severity_tier": 9}).status_code == 422


def test_review_always_releases_stipend():
    pol = {**POLICY, "tau": 5000}  # the fallback policy uses the plan's single tau band
    tx = {"amount": 25000, "severity_tier": 5, "in_disaster_zone": 1, "merchant_category": "clinic"}
    d = fallback_policy.decide({"p_fraud": 0.4, "p_mule": 0.0, "conformal_set": ["legit", "fraud"]}, tx, pol)
    assert d["decision"] == "REVIEW"
    assert d["release_now"] == pol["stipend_cap"] and d["escrow"] == 25000 - pol["stipend_cap"]


def test_empty_conformal_set_means_uncertain():
    from api.bundle import conformal_set
    assert conformal_set(0.5, 0.02) == []  # neither label within qhat: the uncertain middle
    assert conformal_set(0.01, 0.02) == ["legit"] and conformal_set(0.99, 0.02) == ["fraud"]
    tx = {"amount": 25000, "severity_tier": 5, "in_disaster_zone": 1, "merchant_category": "clinic"}
    pol = {**POLICY, "tau": 1.0}  # harm gap alone would not trigger REVIEW
    d = fallback_policy.decide({"p_fraud": 0.02, "p_mule": 0.0, "conformal_set": []}, tx, pol)
    assert d["decision"] == "REVIEW"


def test_mule_override_holds():
    tx = {"amount": 500, "severity_tier": 5, "in_disaster_zone": 1, "merchant_category": "pharmacy"}
    d = fallback_policy.decide({"p_fraud": 0.01, "p_mule": 0.95, "conformal_set": ["legit"]}, tx, POLICY)
    assert d["decision"] == "HOLD"


def test_ledger_has_no_raw_ids_and_verifies(client):
    client.post("/api/v1/evaluate", json=MEENA)
    raw = main.svc.ledger.path.read_text()
    assert "P9000001" not in raw and "M9000001" not in raw
    for rec in raw.splitlines():
        payload = json.loads(rec)["payload"]
        assert find_raw_ids(json.dumps(payload["facts"] if "facts" in payload else {})) == []
    v = client.get("/api/v1/ledger/verify").json()
    assert v["ok"] and v["records"] >= 2


def test_scenarios_run_from_live_engine(client):
    scs = client.get("/api/v1/scenarios").json()["scenarios"]
    assert len(scs) == 6
    out = client.post("/api/v1/scenarios/3/run").json()
    assert out["preloaded_events"] > 27
    rf = out["result"]["recipient_features"]
    assert rf["fan_in_15m"] == 28 and rf["forward_within_10m_ratio"] > 0.5 and rf["mci"] > 0
    # running it again starts from a clean window
    again = client.post("/api/v1/scenarios/3/run").json()
    assert again["result"]["recipient_features"]["fan_in_15m"] == 28


def test_queue_appeal_and_auto_release(client):
    big = {**MEENA, "recipient_id": "M9000099", "amount": 25000, "merchant_category": "clinic", "hour": 14,
           "policy": {"tau": 1e12}}  # everything within tau -> REVIEW
    r = client.post("/api/v1/evaluate", json=big).json()
    assert r["decision"] == "REVIEW"
    eid = r["explain_id"]
    assert client.post(f"/api/v1/appeal/{eid}", json={"note": "medicine"}).json()["appealed"]
    items = client.get("/api/v1/queue").json()["items"]
    assert items[0]["explain_id"] == eid  # appeals jump the queue
    assert eid in client.post("/api/v1/queue/advance-clock?hours=49").json()["released"]
    assert client.post(f"/api/v1/queue/{eid}", json={"action": "deny"}).status_code == 409
    assert client.get("/api/v1/ledger/verify").json()["ok"]


def test_analyst_decision(client):
    r = client.post("/api/v1/evaluate", json={**MEENA, "recipient_id": "M9000098", "amount": 9000,
                                              "policy": {"tau": 1e12}}).json()
    out = client.post(f"/api/v1/queue/{r['explain_id']}", json={"action": "approve", "analyst": "kaustub"}).json()
    assert out["status"] == "approved"


def test_explain_masked(client):
    r = client.post("/api/v1/evaluate", json=MEENA).json()
    ex = client.get(f"/api/v1/explain/{r['explain_id']}").json()
    assert ex["granite"]["card"]
    assert find_raw_ids(json.dumps(ex["masked_facts"])) == []
    assert find_raw_ids(ex["granite"]["prompt"]) == []


def test_replay_runs(client):
    out = client.post("/api/v1/replay", json={"per_hour": 8}).json()
    assert len(out["hours"]) == 72
    t = out["totals"]
    assert t["legacy"]["victim_payments"] == t["nyaya"]["victim_payments"] > 0
    assert out["legacy"]["threshold_source"].startswith("computed")


def test_sim_hooks_503_until_ready(client):
    assert client.get("/api/v1/pareto").status_code == 503


def test_system(client):
    s = client.get("/api/v1/system").json()
    assert s["models"]["kind"] == "stub" and "missing artifacts" in s["models"]["fallback_reason"]
    assert s["ledger"]["records"] >= 1
