import json

import pytest

from explain.card import Granite, build_prompt, check_output, inr, template_card
from explain.masker import RawIdLeak, assert_no_raw_ids, find_raw_ids, mask_facts
from explain.notices import Notices
from explain.policy import FIXTURE_PATH, PolicyIndex

RESULT = {
    "decision": "REVIEW", "release_now": 3000, "escrow": 22000, "p_fraud": 0.41, "p_mule": 0.03,
    "conformal_set": ["legit", "fraud"],
    "reasons": [{"feature": "new_device", "value": 1, "contribution": 0.8},
                {"feature": "amount_to_balance", "value": 0.8, "contribution": 0.5},
                {"feature": "in_disaster_zone", "value": 1, "contribution": -0.6}],
    "policy_clause": {"id": "4.2", "title": "Survival stipend"},
}
TX = {"sender_id": "P9000002", "recipient_id": "M9000002", "device_id": "D0000042", "subnet": "10.0.3.0/24",
      "tx_id": "T00000042", "amount": 25000, "merchant_category": "clinic", "hour": 14, "in_disaster_zone": 1,
      "severity_tier": 5}


# ---------- masker: the test that must fail on any raw id ----------
@pytest.mark.parametrize("raw", ["P9000002", "M000123", "T00000042", "C1231006815", "10.0.3.0/24",
                                 "192.168.1.7", "9876543210", "a3f5c2d19e8b7a6f0c1d", "meena@okaxis"])
def test_raw_ids_detected(raw):
    with pytest.raises(RawIdLeak):
        assert_no_raw_ids(f"payment from {raw} flagged")


def test_amounts_and_clauses_are_not_ids():
    assert find_raw_ids("₹25,000 held; ₹3,000 now; policy 4.2; severity 5; p=0.41; 48 h") == []


def test_mask_facts_drops_every_identifier():
    facts = mask_facts(RESULT, TX, {"escrow_hours": 48})
    blob = json.dumps(facts)
    for k in ("sender_id", "recipient_id", "device_id", "subnet", "tx_id"):
        assert TX[k] not in blob
    assert facts["decision"] == "REVIEW" and facts["escrow"] == 22000


def test_mask_facts_rejects_injected_category():
    facts = mask_facts(RESULT, {**TX, "merchant_category": "P1234567"}, {})
    assert facts["merchant_category"] == "other"


def test_prompt_has_no_raw_ids():
    assert_no_raw_ids(build_prompt(mask_facts(RESULT, TX, {})))


# ---------- cards ----------
def test_inr_grouping():
    assert inr(2500000) == "₹25,00,000" and inr(22000) == "₹22,000" and inr(640) == "₹640"


def test_template_card_mentions_amounts_and_clause():
    card = template_card(mask_facts(RESULT, TX, {"escrow_hours": 48}))
    assert "₹3,000" in card and "₹22,000" in card and "4.2" in card


def test_check_output_rejects_invented_numbers():
    f = mask_facts(RESULT, TX, {"escrow_hours": 48})
    ok, _ = check_output("₹3,000 was sent now and ₹22,000 is held in escrow for 48 hours (policy 4.2).", f)
    assert ok
    ok, why = check_output("₹5,000 was sent now and the rest is held in escrow for 48 hours.", f)
    assert not ok and "5,000" in why


def test_granite_missing_model_falls_back(tmp_path):
    g = Granite(path=tmp_path / "missing.gguf")
    out = g.rewrite(mask_facts(RESULT, TX, {}))
    assert out["source"] == "template" and out["card"]


# ---------- policy + notices ----------
def test_bm25_picks_stipend_clause_for_review():
    idx = PolicyIndex(FIXTURE_PATH)
    c = idx.for_decision("REVIEW", TX, ["new or borrowed phone"], mule_flag=False)
    assert c["id"] == "4.2"


def test_bm25_picks_mule_clause_for_ring():
    idx = PolicyIndex(FIXTURE_PATH)
    c = idx.for_decision("HOLD", TX, ["payee forwards money within 10 min"], mule_flag=True)
    assert c["id"] == "6.2"


def test_notice_fixture_is_english_only():
    n = Notices().render("REVIEW", 25000, 3000, 22000, 48)
    assert "₹3,000" in n["en"] and "₹22,000" in n["en"]
    if n["source"] == "fixture":
        assert n["ta"] is None and n["hi"] is None
