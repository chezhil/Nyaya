import json
import secrets

import pytest

from ledger import Ledger, decrypt, encrypt


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "ledger.jsonl", key=secrets.token_bytes(32))


def test_chain_verifies(ledger):
    for i in range(5):
        ledger.append("decision", {"i": i, "decision": "RELEASE"})
    v = ledger.verify()
    assert v["ok"] and v["records"] == 5 and v["head"] == ledger.head


def test_tamper_detected(ledger):
    for i in range(4):
        ledger.append("decision", {"i": i, "amount": 100 * i})
    lines = ledger.path.read_text().splitlines()
    rec = json.loads(lines[2])
    rec["payload"]["amount"] = 1  # edit one field, keep the stored hash
    lines[2] = json.dumps(rec)
    ledger.path.write_text("\n".join(lines) + "\n")
    v = ledger.verify()
    assert not v["ok"] and v["first_bad_seq"] == 2


def test_deleted_line_detected(ledger):
    for i in range(4):
        ledger.append("decision", {"i": i})
    lines = ledger.path.read_text().splitlines()
    del lines[1]
    ledger.path.write_text("\n".join(lines) + "\n")
    v = ledger.verify()
    assert not v["ok"] and v["first_bad_seq"] == 1


def test_reopen_continues_chain(tmp_path):
    key = secrets.token_bytes(32)
    a = Ledger(tmp_path / "l.jsonl", key=key)
    a.append("decision", {"x": 1})
    b = Ledger(tmp_path / "l.jsonl", key=key)
    b.append("decision", {"x": 2})
    assert len(b) == 2 and b.verify()["ok"]


def test_escrow_encrypted(ledger):
    rec = ledger.append("decision", {"decision": "REVIEW"}, escrow={"amount": 22000, "account": "P0000001"})
    raw = ledger.path.read_text()
    assert "P0000001" not in raw and "22000" not in raw
    assert ledger.open_escrow(rec["seq"]) == {"amount": 22000, "account": "P0000001"}


def test_gcm_rejects_tampered_ciphertext():
    key = secrets.token_bytes(32)
    blob = encrypt(key, {"a": 1})
    blob["ct"] = blob["ct"][:-4] + ("AAAA" if blob["ct"][-4:] != "AAAA" else "BBBB")
    with pytest.raises(ValueError):
        decrypt(key, blob)
