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


def test_clause_follows_decision_basis_not_reason_labels():
    idx = PolicyIndex(FIXTURE_PATH)
    peace = {**TX, "in_disaster_zone": 0, "severity_tier": 0}
    labels = ["mule-ring centrality", "payee forwards money within 10 min", "new or borrowed phone"]
    assert idx.for_decision("RELEASE", TX, labels, mule_flag=False)["id"] == "3.1"
    assert idx.for_decision("HOLD", peace, labels, mule_flag=False)["id"] == "6.1"  # harm HOLD, not the mule override
    none = idx.for_decision("RELEASE", peace, labels, mule_flag=False)  # no clause covers a routine release
    assert none["id"] is None and none["basis"] == "routine"


def test_demo_scenarios_never_cite_a_clause_tagged_for_another_decision():
    from explain.policy import POLICY_PATH, _TAG

    if not POLICY_PATH.exists():
        pytest.skip("docs/relief_policy.md missing")
    idx = PolicyIndex(POLICY_PATH)
    scenarios = json.loads((POLICY_PATH.parent.parent / "data" / "scenarios" / "demo_scenarios.json").read_text())
    for s in scenarios["scenarios"]:
        for decision in ("RELEASE", "REVIEW", "HOLD"):
            for mule in (False, True):
                c = idx.for_decision(decision, s["tx"], [], mule)
                tags = set(_TAG.findall(c["title"] or ""))
                assert not tags or decision in tags, (s["n"], decision, c["id"])


def test_notice_fixture_is_english_only():
    n = Notices().render("REVIEW", 25000, 3000, 22000, 48)
    assert "₹3,000" in n["en"] and "₹22,000" in n["en"]
    if n["source"] == "fixture":
        assert n["ta"] is None and n["hi"] is None


def test_few_shot_examples_pass_their_own_check():
    from explain.card import FEW_SHOT
    assert {f["decision"] for f, _ in FEW_SHOT} == {"RELEASE", "REVIEW", "HOLD"}
    for facts, text in FEW_SHOT:
        assert check_output(text, facts) == (True, "ok"), text


def test_review_card_saying_released_in_full_is_rejected():
    facts = {"decision": "REVIEW", "amount": 25000, "release_now": 3000, "escrow": 22000, "escrow_hours": 48,
             "severity_tier": 5, "hour": 14, "p_fraud": 0.92, "p_mule": 0.01, "clause_id": "CLAUSE-02"}
    ok, why = check_output("The ₹25,000 stipend was reviewed. It was released in full (policy CLAUSE-02).", facts)
    assert not ok and why == "contradicts decision"


def test_non_mule_hold_explained_as_mule_ring_is_rejected():
    facts = {"decision": "HOLD", "amount": 48000, "severity_tier": 0, "hour": 3, "p_fraud": 1.0, "p_mule": 0.0,
             "clause_id": "CLAUSE-10"}
    text = "The ₹48,000 transfer was held because the payee looks like part of a mule ring (policy CLAUSE-10)."
    assert check_output(text, facts) == (False, "mule wording on a non-mule HOLD")
    mule = {**facts, "p_mule": 0.93, "clause_id": "CLAUSE-04"}
    assert check_output(text.replace("CLAUSE-10", "CLAUSE-04"), mule) == (True, "ok")


def test_release_card_mentioning_escrow_or_stipend_is_rejected():
    facts = {"decision": "RELEASE", "amount": 640, "severity_tier": 4, "hour": 2, "p_fraud": 0.26, "p_mule": 0.0,
             "clause_id": "CLAUSE-01"}
    text = ("The ₹640 pharmacy payment was released in full, and the ₹640 pharmacy payment was sent now as a "
            "survival stipend, and the other ₹640 is held in escrow (policy CLAUSE-01).")
    assert check_output(text, facts) == (False, "contradicts decision")
