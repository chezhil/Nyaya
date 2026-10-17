"""Synthetic payment generator: normal customers, displaced disaster victims, account takeovers and mule syndicates.

Usage (inside the `notebook` container on the server):
    python -m data.generate --out ~/shared/data --tag v1
    python -m data.generate --out ~/shared/data --tag redteam_smurf --variant smurf

Everything here is synthetic and labelled as such. Column definitions: data/schema.md.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from data.features import (
    MODEL_B_FEATURES,
    UNKNOWN_ACCOUNT,
    MCITracker,
    RecipientWindow,
    static_account_features,
)

HERE = Path(__file__).resolve().parent
DEFAULT_SCENARIO = HERE / "scenarios" / "chennai_cyclone.json"
VARIANTS = ("base", "smurf", "device_spoof", "slow_drip")
T0 = 1_792_051_200.0  # 2026-10-15 06:30 UTC = 12:00 IST, matches start_hour_of_day in the preset

# median amount (₹) and lognormal sigma per merchant category
AMOUNTS = {
    "grocery": (600, 0.7), "utilities": (1200, 0.6), "telecom": (300, 0.5), "electronics": (8000, 0.8),
    "travel": (2500, 0.8), "pharmacy": (450, 0.8), "fuel": (1500, 0.5), "clinic": (3000, 0.9),
    "jewellery": (20000, 0.9), "cash_out": (3000, 0.8), "p2p": (2000, 1.0), "donation": (500, 0.8),
}
NORMAL_MIX = {
    "grocery": .28, "utilities": .12, "telecom": .10, "electronics": .08, "travel": .08,
    "pharmacy": .10, "fuel": .10, "clinic": .04, "jewellery": .03, "cash_out": .07,
}
DISPLACED_MIX = {"grocery": .26, "pharmacy": .22, "fuel": .10, "clinic": .08, "telecom": .08, "p2p": .20,
                 "cash_out": .06}
MERCHANT_KINDS = [c for c in NORMAL_MIX]
INCOME_BALANCE = {"low": 6000, "mid": 25000, "high": 120000}


@dataclass
class GenConfig:
    n_normal: int = 60000       # includes account takeovers (ato_rate share)
    n_displaced: int = 15000
    n_syndicate: int = 6000     # victim -> mule payments; mule forwards are extra rows
    variant: str = "base"
    seed: int = 7
    scenario: str = str(DEFAULT_SCENARIO)
    ato_rate: float = 0.015
    zone_share: float = 0.35    # share of people and merchants located in the disaster zone
    displaced_share: float = 0.4  # share of zone residents who are displaced
    mules_per_ring: int = 5
    victims_per_mule: tuple = (6, 30)
    n_merchants: int = 1500
    n_ngos: int = 30
    extra: dict = field(default_factory=dict)


class _Gen:
    def __init__(self, cfg: GenConfig):
        if cfg.variant not in VARIANTS:
            raise ValueError(f"variant must be one of {VARIANTS}")
        self.cfg = cfg
        self.rng = np.random.default_rng(cfg.seed)
        sc = json.loads(Path(cfg.scenario).read_text())
        self.severity = np.array(sc["severity_by_hour"], dtype=int)
        self.hours = len(self.severity)
        self.start_hod = int(sc.get("start_hour_of_day", 0))
        self.accounts: list[dict] = []
        self.events: list[dict] = []
        self._dev = 0
        self._net = 0
        self._kind_count: dict[str, int] = {}

    # ---------- helpers ----------
    def new_device(self) -> str:
        self._dev += 1
        return f"D{self._dev:07d}"

    def new_subnet(self) -> str:
        self._net += 1
        return f"10.{self._net // 65536 % 256}.{self._net // 256 % 256}.{self._net % 256}/24"

    def hod(self, ts: float) -> int:
        return int((self.start_hod * 3600 + ts - T0) // 3600) % 24

    def sev(self, ts: float) -> int:
        h = int((ts - T0) // 3600)
        return int(self.severity[min(max(h, 0), self.hours - 1)])

    def amount(self, cat: str) -> float:
        med, sig = AMOUNTS[cat]
        return float(round(max(20.0, self.rng.lognormal(math.log(med), sig)), 2))

    def sample_hours(self, n: int, weights: np.ndarray) -> np.ndarray:
        w = weights / weights.sum()
        h = self.rng.choice(self.hours, size=n, p=w)
        return T0 + h * 3600 + self.rng.uniform(0, 3600, size=n)

    def hour_weights(self, night_boost: float, day: float = 1.0, night: float = 0.2) -> np.ndarray:
        w = np.empty(self.hours)
        for h in range(self.hours):
            hod = (self.start_hod + h) % 24
            w[h] = night * night_boost if (hod >= 22 or hod < 6) else (day if 8 <= hod < 22 else 0.5)
        return w

    # ---------- accounts ----------
    def build_accounts(self):
        c, rng = self.cfg, self.rng
        n_persons = max(2000, (c.n_normal + c.n_displaced) // 4)
        # Benign sharing that real fraud signals have to see past:
        home_nets = [self.new_subnet() for _ in range(max(1, n_persons // 4))]   # broadband / carrier pools
        market_nets = [self.new_subnet() for _ in range(max(1, c.n_merchants // 4))]  # shops on one network
        camp_nets = [self.new_subnet() for _ in range(10)]                        # relief-camp Wi-Fi
        bc_devices = [self.new_device() for _ in range(max(1, n_persons // 200))]  # bank-mitra agent phones
        for i in range(n_persons):
            in_zone = rng.random() < c.zone_share
            band = rng.choice(["low", "mid", "high"], p=[.6, .32, .08] if in_zone else [.4, .43, .17])
            displaced = in_zone and rng.random() < c.displaced_share
            # recently opened accounts (Jan Dhan drives, relief accounts), more common in the zone
            new_acct = rng.random() < (0.12 if in_zone else 0.06)
            age = rng.uniform(1, 60) if new_acct else min(6000, max(30, rng.lognormal(math.log(1100), 0.8)))
            # accounts opened through a bank-mitra (business correspondent) carry the agent's device
            dev = bc_devices[int(rng.integers(len(bc_devices)))] if band == "low" and rng.random() < 0.12 \
                else self.new_device()
            net = camp_nets[int(rng.integers(len(camp_nets)))] if displaced and rng.random() < 0.2 \
                else home_nets[int(rng.integers(len(home_nets)))]
            self.accounts.append({
                "account_id": f"P{i:07d}", "kind": "person", "account_age_days": float(age),
                "device_id": dev, "subnet": net,
                "in_zone": int(in_zone), "displaced": int(displaced),
                "income_band": band, "merchant_category": "", "ring_id": -1, "is_mule": 0,
            })
        # 8% of people share a family phone with someone else
        persons = [a for a in self.accounts]
        for b in persons:
            if rng.random() < 0.08:
                b["device_id"] = persons[int(rng.integers(len(persons)))]["device_id"]
        for i in range(c.n_merchants):
            self.accounts.append({
                "account_id": f"M{i:06d}", "kind": "merchant",
                "account_age_days": float(rng.uniform(30, 6000)),
                "device_id": self.new_device(), "subnet": market_nets[int(rng.integers(len(market_nets)))],
                "in_zone": int(rng.random() < c.zone_share), "displaced": 0, "income_band": "",
                "merchant_category": MERCHANT_KINDS[i % len(MERCHANT_KINDS)], "ring_id": -1, "is_mule": 0,
            })
        for i in range(c.n_ngos):
            self.accounts.append({
                "account_id": f"N{i:04d}", "kind": "ngo", "account_age_days": float(rng.uniform(900, 5000)),
                "device_id": self.new_device(), "subnet": self.new_subnet(), "in_zone": 1, "displaced": 0,
                "income_band": "", "merchant_category": "donation", "ring_id": -1, "is_mule": 0,
            })
        self.by_id = {a["account_id"]: a for a in self.accounts}
        self.persons = [a["account_id"] for a in self.accounts if a["kind"] == "person"]
        self.zone_persons = [a["account_id"] for a in self.accounts if a["kind"] == "person" and a["in_zone"]]
        self.displaced = [a["account_id"] for a in self.accounts if a["displaced"]]
        self.merchants_by_cat: dict[str, dict[int, list[str]]] = {}
        for a in self.accounts:
            if a["kind"] == "merchant":
                self.merchants_by_cat.setdefault(a["merchant_category"], {0: [], 1: []})[a["in_zone"]].append(
                    a["account_id"])
        self.ngos = [a["account_id"] for a in self.accounts if a["kind"] == "ngo"]
        self.home_nets = home_nets

    def add_account(self, prefix: str, kind: str, age: float, device: str, subnet: str, ring: int = -1) -> str:
        n = self._kind_count.get(kind, 0)
        self._kind_count[kind] = n + 1
        aid = f"{prefix}{n:06d}"
        acc = {"account_id": aid, "kind": kind, "account_age_days": float(age), "device_id": device,
               "subnet": subnet, "in_zone": 0, "displaced": 0, "income_band": "", "merchant_category": "",
               "ring_id": ring, "is_mule": int(kind in ("mule", "cashout"))}
        self.accounts.append(acc)
        self.by_id[aid] = acc
        return aid

    def pick_merchant(self, cat: str, in_zone: bool, hot: bool = False) -> str:
        pool = self.merchants_by_cat[cat][int(in_zone)] or self.merchants_by_cat[cat][1 - int(in_zone)]
        if hot and self.rng.random() < 0.6:
            pool = pool[:20]  # relief-camp merchants that get crowded during the disaster
        return pool[int(self.rng.integers(len(pool)))]

    # ---------- populations ----------
    def ev(self, **kw):
        base = {"amount": None, "drain_frac": None, "src_idx": None, "forward_frac": None,
                "device_id": None, "is_fraud": 0, "variant": self.cfg.variant}
        base.update(kw)
        self.events.append(base)
        return len(self.events) - 1

    def gen_normal(self):
        c, rng = self.cfg, self.rng
        n_ato = int(round(c.n_normal * c.ato_rate))
        n = c.n_normal - n_ato
        ts_all = self.sample_hours(n, self.hour_weights(night_boost=1.0))
        cats = list(NORMAL_MIX)
        cat_p = np.array(list(NORMAL_MIX.values()))
        for ts in ts_all:
            s = self.persons[int(rng.integers(len(self.persons)))]
            acc = self.by_id[s]
            sev = self.sev(ts)
            in_dz = int(acc["in_zone"] and sev > 0)
            u = rng.random()
            if sev > 0 and u < 0.04:
                cat, r, typ = "donation", self.ngos[int(rng.integers(len(self.ngos)))], "TRANSFER"
            elif u < 0.22:
                cat, r, typ = "p2p", self.persons[int(rng.integers(len(self.persons)))], "TRANSFER"
            else:
                cat = cats[rng.choice(len(cats), p=cat_p / cat_p.sum())]
                r = self.pick_merchant(cat, bool(acc["in_zone"]) if rng.random() < .7 else not acc["in_zone"])
                typ = "CASH_OUT" if cat == "cash_out" else "PAYMENT"
            travel = rng.random() < 0.04
            # 3% move (almost) the whole balance: rent, a family transfer, a cash withdrawal
            drain = float(rng.uniform(0.85, 1.0)) if cat in ("p2p", "cash_out") and rng.random() < 0.12 else None
            self.ev(ts=ts, sender_id=s, recipient_id=r, type=typ, amount=None if drain else self.amount(cat),
                    drain_frac=drain, merchant_category=cat,
                    geo_shift_km=float(rng.uniform(50, 800) if travel else rng.exponential(4.0)),
                    new_device=int(rng.random() < 0.04), in_disaster_zone=in_dz,
                    severity_tier=sev if in_dz else 0, population="normal")
        # NGOs pay suppliers every 20 minutes while the disaster is on (benign pass-through accounts)
        for h in range(self.hours):
            if self.severity[h] == 0:
                continue
            for half in (0, 1200, 2400):
                for ngo in self.ngos:
                    ts = T0 + h * 3600 + half + float(rng.uniform(0, 600))
                    cat = "grocery" if rng.random() < .6 else "pharmacy"
                    self.ev(ts=ts, sender_id=ngo, recipient_id=self.pick_merchant(cat, True), type="TRANSFER",
                            drain_frac=0.7, merchant_category=cat, geo_shift_km=float(rng.exponential(2.0)),
                            new_device=0, in_disaster_zone=1, severity_tier=int(self.severity[h]),
                            population="ngo_payout")
        # account takeovers: drain to a fresh account, often from a new device far away
        ts_all = self.sample_hours(n_ato, self.hour_weights(night_boost=4.0))
        for ts in ts_all:
            s = self.persons[int(rng.integers(len(self.persons)))]
            if rng.random() < 0.4:  # buys goods that resell easily
                cat = str(rng.choice(["electronics", "jewellery", "telecom", "fuel", "travel"]))
                r = self.pick_merchant(cat, rng.random() < 0.5)
            else:
                cat = str(rng.choice(["p2p", "cash_out"], p=[.6, .4]))
                r = self.add_account("A", "ato_dest", rng.uniform(0, 20), self.new_device(), self.new_subnet())
            sev = self.sev(ts)
            spoof = sev > 0 and rng.random() < 0.15
            local = rng.random() < 0.4  # SIM swap / someone nearby who knows the victim
            typ = "CASH_OUT" if cat == "cash_out" else ("TRANSFER" if cat == "p2p" else "PAYMENT")
            self.ev(ts=ts, sender_id=s, recipient_id=r, type=typ,
                    drain_frac=float(rng.uniform(0.9, 1.0) if rng.random() < 0.65 else rng.uniform(0.3, 0.8)),
                    merchant_category=str(cat),
                    geo_shift_km=float(rng.exponential(10.0) if local else rng.lognormal(math.log(400), 0.7)),
                    new_device=int(rng.random() < 0.7),
                    in_disaster_zone=int(spoof), severity_tier=sev if spoof else 0, population="ato", is_fraud=1)

    def gen_displaced(self):
        c, rng = self.cfg, self.rng
        w = np.where(self.severity >= 2, self.severity.astype(float) ** 1.5, 0.0)
        w = w * np.array([2.5 if ((self.start_hod + h) % 24 >= 22 or (self.start_hod + h) % 24 < 6) else 1.0
                          for h in range(self.hours)])
        cats = list(DISPLACED_MIX)
        cat_p = np.array(list(DISPLACED_MIX.values()))
        for ts in self.sample_hours(c.n_displaced, w):
            s = self.displaced[int(rng.integers(len(self.displaced)))]
            cat = cats[rng.choice(len(cats), p=cat_p)]
            if cat == "p2p":
                r, typ = self.persons[int(rng.integers(len(self.persons)))], "TRANSFER"
            else:
                r, typ = self.pick_merchant(cat, True, hot=True), "PAYMENT"
            if cat == "cash_out":
                typ = "CASH_OUT"
            amt = float(round(rng.uniform(2000, 40000), 2)) if cat == "clinic" else self.amount(cat)
            # 20% spend (almost) everything left: the last of the relief money
            drain = float(rng.uniform(0.85, 1.0)) if rng.random() < 0.2 else None
            self.ev(ts=ts, sender_id=s, recipient_id=r, type=typ, amount=None if drain else amt,
                    drain_frac=drain, merchant_category=cat,
                    geo_shift_km=float(min(800, rng.lognormal(math.log(120), 0.9))),
                    new_device=int(rng.random() < 0.7), in_disaster_zone=1, severity_tier=self.sev(ts),
                    population="displaced")

    def gen_collectors(self):
        """Volunteers who collect UPI donations from neighbours and pass them on to camps within minutes.
        Legitimate fan-in + fast forwarding, often from new accounts on shared phones: Model B's hard case."""
        c, rng = self.cfg, self.rng
        w = np.where(self.severity >= 2, self.severity.astype(float), 0.0)
        young = [p for p in self.zone_persons if self.by_id[p]["account_age_days"] < 60]
        for _ in range(max(5, c.n_displaced // 250)):
            pool = young if young and rng.random() < 0.5 else self.zone_persons
            col = pool[int(rng.integers(len(pool)))]
            for _ in range(int(rng.integers(1, 4))):
                start = float(self.sample_hours(1, w)[0])
                span = float(rng.uniform(600, 1800))
                for _ in range(int(rng.integers(5, 21))):
                    ts = start + float(rng.uniform(0, span))
                    d = self.persons[int(rng.integers(len(self.persons)))]
                    sev = self.sev(ts)
                    in_dz = int(self.by_id[d]["in_zone"] and sev > 0)
                    self.ev(ts=ts, sender_id=d, recipient_id=col, type="TRANSFER", amount=self.amount("donation"),
                            merchant_category="p2p", geo_shift_km=float(rng.exponential(4.0)),
                            new_device=int(rng.random() < 0.04), in_disaster_zone=in_dz,
                            severity_tier=sev if in_dz else 0, population="collector_donation")
                for _ in range(int(rng.integers(1, 4))):
                    ts = start + span * float(rng.uniform(0.3, 1.0)) + float(rng.uniform(60, 1200))
                    if rng.random() < 0.5:
                        r, cat = self.displaced[int(rng.integers(len(self.displaced)))], "p2p"
                    else:
                        cat = "pharmacy" if rng.random() < 0.5 else "grocery"
                        r = self.pick_merchant(cat, True, hot=True)
                    self.ev(ts=ts, sender_id=col, recipient_id=r, type="TRANSFER",
                            drain_frac=float(rng.uniform(0.3, 0.6)), merchant_category=cat,
                            geo_shift_km=float(rng.exponential(5.0)), new_device=int(rng.random() < 0.3),
                            in_disaster_zone=1, severity_tier=max(1, self.sev(ts)), population="collector_payout")

    def gen_syndicate(self):
        c, rng, v = self.cfg, self.rng, self.cfg.variant
        w = np.where(self.severity >= 3, self.severity.astype(float), 0.0)
        made, ring = 0, 0
        while made < c.n_syndicate:
            m = c.mules_per_ring * (3 if v == "smurf" else 1)
            lo, hi = c.victims_per_mule
            if v == "smurf":
                lo, hi = max(1, lo // 3), max(2, hi // 3)
            start = float(self.sample_hours(1, w)[0])
            burst = float(rng.uniform(600, 1800))
            ring_dev = [self.new_device(), self.new_device()]
            ring_net = self.new_subnet()
            cash = [self.add_account("K", "cashout", rng.uniform(5, 120), ring_dev[0], ring_net, ring)
                    for _ in range(2)]
            for j in range(m):
                recruited = rng.random() < 0.45  # a real customer renting out an old account
                if v == "device_spoof":
                    dev, net = self.new_device(), self.new_subnet()
                else:
                    dev = ring_dev[j % 2] if rng.random() < 0.6 else self.new_device()
                    net = self.home_nets[int(rng.integers(len(self.home_nets)))] if recruited else ring_net
                age = rng.uniform(200, 3000) if recruited else rng.uniform(1, 45)
                mule = self.add_account("U", "mule", age, dev, net, ring)
                for _ in range(int(rng.integers(lo, hi + 1))):
                    if made >= c.n_syndicate:
                        break
                    ts = start + float(rng.uniform(0, burst))
                    s = self.zone_persons[int(rng.integers(len(self.zone_persons)))]
                    idx = self.ev(ts=ts, sender_id=s, recipient_id=mule, type="TRANSFER",
                                  drain_frac=float(rng.uniform(0.85, 1.0) if rng.random() < 0.75
                                                   else rng.uniform(0.5, 0.85)),
                                  merchant_category="p2p",
                                  geo_shift_km=float(rng.lognormal(math.log(8), 0.8)),
                                  new_device=int(rng.random() < (0.10 if v == "device_spoof" else 0.6)),
                                  in_disaster_zone=1, severity_tier=max(1, self.sev(ts)),
                                  population="syndicate", is_fraud=1)
                    made += 1
                    if v == "slow_drip":
                        delay = rng.uniform(720, 2400)
                    else:
                        delay = rng.uniform(60, 480) if rng.random() < 0.7 else rng.uniform(480, 1500)
                    self.ev(ts=ts + float(delay), sender_id=mule, recipient_id=cash[int(rng.integers(2))],
                            type="TRANSFER", src_idx=idx, forward_frac=float(rng.uniform(0.95, 0.99)),
                            merchant_category="p2p", geo_shift_km=float(rng.exponential(5.0)), new_device=0,
                            in_disaster_zone=1, severity_tier=max(1, self.sev(ts)),
                            population="syndicate_forward", is_fraud=1)
            ring += 1
        self.n_rings = ring

    # ---------- sequential pass: balances + point-in-time recipient features ----------
    def materialise(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        rng = self.rng
        acc_df = pd.DataFrame(self.accounts)
        static = static_account_features(acc_df)
        bal = {}
        for a in self.accounts:
            k = a["kind"]
            if k == "person" and a["account_age_days"] < 60:
                bal[a["account_id"]] = float(rng.uniform(0, 800))  # newly opened, barely funded
            elif k == "person":
                bal[a["account_id"]] = float(rng.lognormal(math.log(INCOME_BALANCE[a["income_band"]]), 0.8))
            elif k == "merchant":
                bal[a["account_id"]] = float(rng.lognormal(math.log(200000), 0.8))
            elif k == "ngo":
                bal[a["account_id"]] = float(rng.lognormal(math.log(50000), 0.5))
            elif k == "mule" and a["account_age_days"] >= 200:
                bal[a["account_id"]] = float(rng.lognormal(math.log(8000), 0.8))  # recruited, lived-in account
            elif k == "mule":
                bal[a["account_id"]] = float(rng.uniform(0, 1000))
            elif k == "cashout":
                bal[a["account_id"]] = float(rng.uniform(0, 3000))
            else:
                bal[a["account_id"]] = 0.0
        order = sorted(range(len(self.events)), key=lambda i: self.events[i]["ts"])
        filled = {}
        window, mci = RecipientWindow(), MCITracker()
        rows = []
        for n, i in enumerate(order):
            e = self.events[i]
            s, r, ts = e["sender_id"], e["recipient_id"], float(e["ts"])
            old_o = bal[s]
            if e["src_idx"] is not None:
                amt = min(old_o, filled.get(e["src_idx"], 0.0) * e["forward_frac"])
                if amt <= 0:
                    continue
            elif e["drain_frac"] is not None:
                if old_o < 100:
                    old_o += float(rng.uniform(5000, 20000))  # relief credit / salary landed earlier
                amt = old_o * e["drain_frac"]
            else:
                amt = e["amount"]
                if old_o < amt:
                    old_o += amt * float(rng.uniform(1.0, 2.0))  # unrecorded top-up
            amt = float(round(amt, 2))
            filled[i] = amt
            new_o = round(old_o - amt, 2)
            old_d = bal[r]
            new_d = round(old_d + amt, 2)
            bal[s], bal[r] = new_o, new_d
            window.add(ts, s, r, amt)
            mci.add(ts, s, r, amt)
            rf = window.features(r, ts)
            st = static.get(r, UNKNOWN_ACCOUNT)
            sacc = self.by_id[s]
            row = {
                "tx_id": "", "ts": round(ts, 3), "hour": self.hod(ts),
                "sender_id": s, "recipient_id": r, "type": e["type"], "amount": amt,
                "oldbalanceOrg": round(old_o, 2), "newbalanceOrig": new_o,
                "oldbalanceDest": round(old_d, 2), "newbalanceDest": new_d,
                "geo_shift_km": round(e["geo_shift_km"], 2), "new_device": e["new_device"],
                "merchant_category": e["merchant_category"], "in_disaster_zone": e["in_disaster_zone"],
                "severity_tier": e["severity_tier"],
                "device_id": self.new_device() if e["new_device"] else sacc["device_id"],
                "subnet": sacc["subnet"], "population": e["population"], "variant": e["variant"],
                "is_fraud": e["is_fraud"], "is_mule_recipient": self.by_id[r]["is_mule"],
                "sender_income_band": sacc["income_band"],
                **rf, **st, "mci": round(mci.get(r), 6),
            }
            rows.append(row)
            if n % 20000 == 0:
                window.gc(ts)
        tx = pd.DataFrame(rows)
        tx["tx_id"] = [f"T{k:08d}" for k in range(len(tx))]
        return tx, pd.DataFrame(self.accounts)


def generate(cfg: GenConfig | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (payments, accounts). Deterministic for a given config."""
    g = _Gen(cfg or GenConfig())
    g.build_accounts()
    g.gen_normal()
    g.gen_displaced()
    g.gen_collectors()
    g.gen_syndicate()
    return g.materialise()


def recipients_view(tx: pd.DataFrame) -> pd.DataFrame:
    cols = ["tx_id", "ts", "recipient_id"] + MODEL_B_FEATURES + ["is_mule_recipient", "population", "variant"]
    return tx[cols]


def write(tx: pd.DataFrame, accounts: pd.DataFrame, out: Path, tag: str, cfg: GenConfig) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "payments": out / f"nyaya_{tag}.csv.gz",
        "accounts": out / f"accounts_{tag}.csv.gz",
        "recipients": out / f"recipients_{tag}.csv.gz",
    }
    tx.to_csv(paths["payments"], index=False)
    accounts.to_csv(paths["accounts"], index=False)
    recipients_view(tx).to_csv(paths["recipients"], index=False)
    summary = {
        "tag": tag, "config": asdict(cfg), "rows": len(tx), "accounts": len(accounts),
        "by_population": tx["population"].value_counts().to_dict(),
        "fraud_rate": float(tx["is_fraud"].mean()),
        "mule_recipient_rate": float(tx["is_mule_recipient"].mean()),
        "files": {k: str(v) for k, v in paths.items()},
    }
    (out / f"summary_{tag}.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=Path.home() / "shared" / "data")
    p.add_argument("--tag", default="v1")
    p.add_argument("--variant", choices=VARIANTS, default="base")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--n-normal", type=int, default=GenConfig.n_normal)
    p.add_argument("--n-displaced", type=int, default=GenConfig.n_displaced)
    p.add_argument("--n-syndicate", type=int, default=GenConfig.n_syndicate)
    p.add_argument("--scenario", default=str(DEFAULT_SCENARIO))
    a = p.parse_args(argv)
    cfg = GenConfig(n_normal=a.n_normal, n_displaced=a.n_displaced, n_syndicate=a.n_syndicate,
                    variant=a.variant, seed=a.seed, scenario=a.scenario)
    t = time.time()
    tx, acc = generate(cfg)
    summary = write(tx, acc, a.out.expanduser(), a.tag, cfg)
    summary["seconds"] = round(time.time() - t, 1)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
