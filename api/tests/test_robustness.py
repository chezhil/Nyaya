"""Regression tests for state-handling bugs found in review (18 Oct 2026):
restart lost the analyst queue, a failed ledger write left state changed, negative policy overrides were accepted,
and Policy Console what-if calls were recorded as real decisions."""
import secrets

import pytest
from fastapi.testclient import TestClient

import api.main as main
from api.service import Nyaya

REVIEW_TX = {"sender_id": "P9100001", "recipient_id": "M9100001", "type": "PAYMENT", "amount": 25000,
             "oldbalanceOrg": 31000, "hour": 14, "geo_shift_km": 80, "new_device": 1,
             "merchant_category": "clinic", "in_disaster_zone": 1, "severity_tier": 5}


def make(tmp_path, key):
    s = Nyaya(artifacts=tmp_path / "no-artifacts", ledger_path=tmp_path / "ledger.jsonl", accounts_path=None,
              start_workers=False, ledger_key=key)
    s.policy.update(tau=1e12, tau_review=1e12)  # every payment over the cap goes to REVIEW
    return s


@pytest.fixture
def key():
    return secrets.token_bytes(32)


def test_queue_survives_restart(tmp_path, key):
    s1 = make(tmp_path, key)
    a = s1.evaluate(REVIEW_TX)
    b = s1.evaluate({**REVIEW_TX, "recipient_id": "M9100002"})
    assert a["decision"] == b["decision"] == "REVIEW"
    s1.appeal(a["explain_id"], "urgent")
    s1.queue_action(b["explain_id"], "approve", "analyst")
    before = {i["explain_id"]: i for i in s1.queue_list()}

    s2 = make(tmp_path, key)  # same ledger and key: a restarted process
    after = {i["explain_id"]: i for i in s2.queue_list()}
    assert set(after) == set(before)
    qa, qb = after[a["explain_id"]], after[b["explain_id"]]
    assert qa["status"] == "pending" and qa["appealed"] and qa["release_at"] == pytest.approx(before[a["explain_id"]]["release_at"])
    assert qa["release_now"] == round(a["release_now"]) and qa["escrow"] == round(a["escrow"])
    assert qb["status"] == "approved"
    assert s2.explain(a["explain_id"]) is not None  # the explanation is rebuilt too
    # auto-release still works after the restart
    s2.clock_offset = 49 * 3600
    assert s2.auto_release() == [a["explain_id"]]


def test_failed_ledger_write_leaves_escrow_pending(tmp_path, key, monkeypatch):
    s = make(tmp_path, key)
    r = s.evaluate(REVIEW_TX)
    real_append = s.ledger.append

    def failing(kind, *args, **kw):
        if kind == "escrow_auto_release":
            raise OSError("disk full")
        return real_append(kind, *args, **kw)

    monkeypatch.setattr(s.ledger, "append", failing)
    s.clock_offset = 49 * 3600
    out = s.advance_clock(0)
    assert out["released"] == [] and r["explain_id"] in out["failed"]
    assert s.queue[r["explain_id"]]["status"] == "pending"
    assert not any(rec["kind"] == "escrow_auto_release" for rec in s.ledger.records())

    monkeypatch.setattr(s.ledger, "append", real_append)
    assert s.auto_release() == [r["explain_id"]]
    assert s.queue[r["explain_id"]]["status"] == "auto_released"
    assert sum(rec["kind"] == "escrow_auto_release" for rec in s.ledger.records()) == 1


@pytest.mark.parametrize("kind,call", [("analyst_release", lambda s, e: s.queue_action(e, "approve", "a")),
                                       ("appeal", lambda s, e: s.appeal(e, "x"))])
def test_failed_ledger_write_leaves_queue_unchanged(tmp_path, key, monkeypatch, kind, call):
    s = make(tmp_path, key)
    e = s.evaluate(REVIEW_TX)["explain_id"]
    snapshot = dict(s.queue[e])
    monkeypatch.setattr(s.ledger, "append", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        call(s, e)
    assert s.queue[e] == snapshot


def test_failed_decision_write_records_nothing(tmp_path, key, monkeypatch):
    s = make(tmp_path, key)
    monkeypatch.setattr(s.ledger, "append", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        s.evaluate(REVIEW_TX)
    assert s.queue == {} and s.explains == {}
    assert s.store.recipient_features(REVIEW_TX["recipient_id"], 0, None)["fan_in_15m"] == 0


@pytest.fixture
def client(tmp_path, key):
    main.svc = make(tmp_path, key)
    with TestClient(main.app) as c:
        yield c
    main.svc = None


@pytest.mark.parametrize("policy", [{"stipend_cap": -500}, {"beta": -1}, {"theta_mule": 1.5}, {"escrow_hours": 0},
                                    {"alpha": "lots"}, {"not_a_policy_key": 1}])
def test_bad_policy_overrides_rejected(client, policy):
    r = client.post("/api/v1/evaluate", json={**REVIEW_TX, "policy": policy})
    assert r.status_code == 422, r.text


def test_engine_never_pays_out_a_negative_stipend():
    from engine import decide
    import json
    pol = {**json.loads((main.ROOT / "api" / "policy_defaults.json").read_text()), "tau": 1e12, "tau_review": 1e12,
           "stipend_cap": -500}
    d = decide({"p_fraud": 0.2, "p_mule": 0.0, "conformal_set": ["legit"]}, dict(REVIEW_TX), pol)
    assert 0 <= d["release_now"] <= REVIEW_TX["amount"] and d["escrow"] >= 0
    assert d["release_now"] + d["escrow"] == pytest.approx(REVIEW_TX["amount"]) or d["decision"] != "REVIEW"


def test_what_if_has_no_side_effects(client):
    s = main.svc
    real = client.post("/api/v1/evaluate", json=REVIEW_TX).json()
    ledger_len, queue_len = len(s.ledger), len(s.queue)
    fan_in = s.store.recipient_features(REVIEW_TX["recipient_id"], s.store.latest_ts, None)["fan_in_15m"]

    r = client.post("/api/v1/evaluate", json={**REVIEW_TX, "policy": {"stipend_cap": 2000, "alpha": 0.4}})
    assert r.status_code == 200, r.text
    w = r.json()
    assert w["what_if"] is True and w["ledger_hash"] is None and w["explain_id"] is None
    assert w["decision"] == "REVIEW" and w["release_now"] == 2000
    assert len(s.ledger) == ledger_len and len(s.queue) == queue_len
    assert s.store.recipient_features(REVIEW_TX["recipient_id"], s.store.latest_ts, None)["fan_in_15m"] == fan_in
    assert real["what_if"] is False and real["ledger_hash"]


def test_what_if_features_match_a_real_evaluation(tmp_path, key):
    s = make(tmp_path, key)
    s.evaluate({**REVIEW_TX, "recipient_id": "U9100009", "sender_id": "P1"})
    w = s.evaluate({**REVIEW_TX, "recipient_id": "U9100009", "sender_id": "P2"}, {"stipend_cap": 3000})
    real = s.evaluate({**REVIEW_TX, "recipient_id": "U9100009", "sender_id": "P2"})
    assert w["recipient_features"] == real["recipient_features"]
