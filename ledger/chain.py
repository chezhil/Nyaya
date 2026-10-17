"""Tamper-evident decision ledger.

Each record is one JSON line. hash = SHA-256(canonical_json(record without "hash") || prev_hash).
hashlib uses OpenSSL, which uses CPACF (the `msa` instructions) on IBM Z.
Escrow details are encrypted with AES-256-GCM (pycryptodome) before they are written.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path

from Crypto.Cipher import AES

GENESIS = "0" * 64


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()


def record_hash(record: dict, prev_hash: str) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(canonical(body) + prev_hash.encode()).hexdigest()


def load_key(path: Path | None = None) -> bytes:
    """32-byte AES key from $NYAYA_LEDGER_KEY (hex) or a 0600 key file created on first use. Never committed."""
    env = os.environ.get("NYAYA_LEDGER_KEY")
    if env:
        key = bytes.fromhex(env)
        if len(key) != 32:
            raise ValueError("NYAYA_LEDGER_KEY must be 64 hex characters")
        return key
    path = path or Path(os.environ.get("NYAYA_LEDGER_KEY_FILE", Path.home() / ".nyaya" / "ledger.key"))
    if path.exists():
        return bytes.fromhex(path.read_text().strip())
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key.hex())
    return key


def encrypt(key: bytes, data: dict, aad: bytes = b"nyaya-escrow") -> dict:
    nonce = secrets.token_bytes(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    cipher.update(aad)
    ct, tag = cipher.encrypt_and_digest(canonical(data))
    b64 = lambda b: base64.b64encode(b).decode()
    return {"alg": "AES-256-GCM", "nonce": b64(nonce), "ct": b64(ct), "tag": b64(tag)}


def decrypt(key: bytes, blob: dict, aad: bytes = b"nyaya-escrow") -> dict:
    d = lambda s: base64.b64decode(s)
    cipher = AES.new(key, AES.MODE_GCM, nonce=d(blob["nonce"]))
    cipher.update(aad)
    return json.loads(cipher.decrypt_and_verify(d(blob["ct"]), d(blob["tag"])))


class Ledger:
    """Append-only JSONL hash chain. Thread-safe within one process."""

    def __init__(self, path: str | Path, key: bytes | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.key = key if key is not None else load_key()
        self._lock = threading.Lock()
        self._seq, self._head = self._scan_tail()

    def _scan_tail(self) -> tuple[int, str]:
        if not self.path.exists():
            return 0, GENESIS
        seq, head = 0, GENESIS
        with self.path.open("rb") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    seq, head = rec["seq"] + 1, rec["hash"]
        return seq, head

    @property
    def head(self) -> str:
        return self._head

    def __len__(self) -> int:
        return self._seq

    def append(self, kind: str, payload: dict, escrow: dict | None = None) -> dict:
        """payload must already be masked (no raw account IDs). escrow is encrypted before writing."""
        with self._lock:
            rec = {
                "seq": self._seq,
                "ts": round(time.time(), 3),
                "kind": kind,
                "payload": payload,
                "escrow_enc": encrypt(self.key, escrow) if escrow is not None else None,
                "prev_hash": self._head,
            }
            rec["hash"] = record_hash(rec, self._head)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
                f.flush()
                os.fsync(f.fileno())
            self._seq += 1
            self._head = rec["hash"]
            return rec

    def records(self):
        if not self.path.exists():
            return
        with self.path.open("rb") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)

    def verify(self) -> dict:
        """Recompute the chain. Reports the first broken record, if any."""
        t = time.perf_counter()
        prev, n = GENESIS, 0
        if self.path.exists():
            with self.path.open("rb") as f:
                for lineno, line in enumerate(f):
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        return self._bad(n, lineno, "unparseable line", t)
                    if rec.get("seq") != n:
                        return self._bad(n, lineno, f"sequence gap: expected {n}, found {rec.get('seq')}", t)
                    if rec.get("prev_hash") != prev:
                        return self._bad(n, lineno, "prev_hash does not match the previous record", t)
                    if record_hash(rec, prev) != rec.get("hash"):
                        return self._bad(n, lineno, "record content does not match its hash", t)
                    prev, n = rec["hash"], n + 1
        return {"ok": True, "records": n, "head": prev, "algorithm": "SHA-256 (hashlib/OpenSSL)",
                "verify_ms": round((time.perf_counter() - t) * 1000, 3)}

    @staticmethod
    def _bad(seq, lineno, reason, t):
        return {"ok": False, "first_bad_seq": seq, "line": lineno + 1, "reason": reason,
                "verify_ms": round((time.perf_counter() - t) * 1000, 3)}

    def open_escrow(self, seq: int) -> dict | None:
        for rec in self.records():
            if rec["seq"] == seq and rec.get("escrow_enc"):
                return decrypt(self.key, rec["escrow_enc"])
        return None
