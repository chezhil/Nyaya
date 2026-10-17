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


def test_key_validation_env_and_file(tmp_path, monkeypatch):
    from ledger.chain import load_key

    # Invalid length in env
    monkeypatch.setenv("NYAYA_LEDGER_KEY", "00" * 16)  # 16 bytes
    with pytest.raises(ValueError, match="64 hex characters"):
        load_key()

    # Valid in env
    valid_hex = secrets.token_bytes(32).hex()
    monkeypatch.setenv("NYAYA_LEDGER_KEY", valid_hex)
    assert load_key() == bytes.fromhex(valid_hex)
    monkeypatch.delenv("NYAYA_LEDGER_KEY")

    # Invalid length in file (16 bytes)
    bad_key_file = tmp_path / "bad.key"
    bad_key_file.write_text("aa" * 16)
    with pytest.raises(ValueError, match="64 hex characters"):
        load_key(bad_key_file)

    # Empty file
    empty_key_file = tmp_path / "empty.key"
    empty_key_file.write_text("")
    with pytest.raises(ValueError, match="empty"):
        load_key(empty_key_file)


def test_encrypt_decrypt_rejects_invalid_key_length():
    with pytest.raises(ValueError, match="AES-256 key must be exactly 32 bytes"):
        encrypt(b"short", {"a": 1})
    with pytest.raises(ValueError, match="AES-256 key must be exactly 32 bytes"):
        encrypt(b"0" * 16, {"a": 1})
    with pytest.raises(ValueError, match="AES-256 key must be exactly 32 bytes"):
        decrypt(b"0" * 16, {"nonce": "AA==", "ct": "AA==", "tag": "AA=="})


def test_ledger_init_rejects_invalid_key(tmp_path):
    with pytest.raises(ValueError, match="Ledger key must be exactly 32 bytes"):
        Ledger(tmp_path / "test.jsonl", key=b"bad_len")


def test_empty_ledger_file(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.touch()
    led = Ledger(p, key=secrets.token_bytes(32))
    assert len(led) == 0
    v = led.verify()
    assert v["ok"] and v["records"] == 0 and v["head"] == "0" * 64


def test_corrupted_genesis_prev_hash(ledger):
    for i in range(3):
        ledger.append("decision", {"i": i})
    lines = ledger.path.read_text().splitlines()
    rec0 = json.loads(lines[0])
    rec0["prev_hash"] = "1" * 64
    lines[0] = json.dumps(rec0)
    ledger.path.write_text("\n".join(lines) + "\n")
    v = ledger.verify()
    assert not v["ok"]
    assert v["first_bad_seq"] == 0
    assert "prev_hash does not match" in v["reason"]


def test_corrupted_genesis_seq(ledger):
    for i in range(3):
        ledger.append("decision", {"i": i})
    lines = ledger.path.read_text().splitlines()
    rec0 = json.loads(lines[0])
    rec0["seq"] = 1
    lines[0] = json.dumps(rec0)
    ledger.path.write_text("\n".join(lines) + "\n")
    v = ledger.verify()
    assert not v["ok"]
    assert v["first_bad_seq"] == 0
    assert "sequence gap" in v["reason"]


def test_escrow_1byte_flip_detected_by_hash(ledger):
    rec = ledger.append("decision", {"i": 0}, escrow={"amount": 9999})
    lines = ledger.path.read_text().splitlines()
    rec_obj = json.loads(lines[0])
    import base64
    ct_bytes = bytearray(base64.b64decode(rec_obj["escrow_enc"]["ct"]))
    ct_bytes[0] ^= 0x01
    rec_obj["escrow_enc"]["ct"] = base64.b64encode(ct_bytes).decode()
    lines[0] = json.dumps(rec_obj)
    ledger.path.write_text("\n".join(lines) + "\n")

    # Hash verification detects content modification
    v = ledger.verify()
    assert not v["ok"]
    assert "record content does not match its hash" in v["reason"]

    # Decryption fails MAC check
    with pytest.raises(ValueError):
        ledger.open_escrow(0)


def test_truncated_chain_detected_with_expected_state(ledger):
    for i in range(5):
        ledger.append("decision", {"i": i})
    expected_head = ledger.head
    expected_seq = len(ledger)

    # Truncate file to 3 records
    lines = ledger.path.read_text().splitlines()
    ledger.path.write_text("\n".join(lines[:3]) + "\n")

    v = ledger.verify(expected_head=expected_head, expected_seq=expected_seq)
    assert not v["ok"]
    assert "chain truncated" in v["reason"]


def test_concurrent_appends_across_instances(tmp_path):
    import threading
    key = secrets.token_bytes(32)
    lpath = tmp_path / "concurrent.jsonl"
    init_led = Ledger(lpath, key=key)
    init_led.append("init", {"start": True})

    def worker(worker_id):
        worker_led = Ledger(lpath, key=key)
        for i in range(25):
            worker_led.append("worker", {"wid": worker_id, "i": i})

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    verifier = Ledger(lpath, key=key)
    v = verifier.verify()
    assert v["ok"]
    assert v["records"] == 1 + (4 * 25)

