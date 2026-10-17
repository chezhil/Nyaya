# Audit Report: Scalar vs. Frame Feature Parity in `data/features.py`

**Auditor:** Aaditya (Frontend, Story & Policy Lead)  
**Target Owner:** Chezhil (Data & Feature Pipeline Lead)  
**Date:** October 2026  
**Status:** Actionable Findings & Recommended Fix for `data/features.py`  

---

## Executive Summary
While conducting the end-to-end audit between client payment payloads and model feature generation (`data/features.py`), we identified three subtle discrepancies between the single-transaction scalar function `tx_features(tx: dict)` and the vectorised DataFrame function `tx_features_frame(df: pd.DataFrame)`.

Because `tx_features` is invoked during real-time online inference (via `api/` and `engine/`) while `tx_features_frame` is used for offline batch generation and training data preprocessing, any mathematical divergence violates the contract:
> *"One implementation for both sides, so training and serving can't drift."* (`data/features.py:3`)

Per `AGENTS.md` and `CONTRACTS.md` ownership rules, the `data/` directory is owned by Chezhil. This document details the three root causes, the recommended drop-in fix, and a parity verification test.

---

## 1. Identified Discrepancies

### Finding 1.1: Case Sensitivity in Transaction Type (`type_code`)
- **Scalar Path (`tx_features:60`):**
  ```python
  "type_code": TX_TYPES.get(str(tx.get("type", "PAYMENT")).upper(), 0)
  ```
  Applies `.upper()`, correctly mapping `"transfer"` -> `1` (`TRANSFER`).
- **Frame Path (`tx_features_frame:85`):**
  ```python
  out["type_code"] = df["type"].map(TX_TYPES).fillna(0).astype(int)
  ```
  Performs direct mapping without case normalization. If incoming rows contain lowercase or titlecase strings (e.g., `"transfer"` or `"Payment"`), `.map(TX_TYPES)` evaluates to `NaN` and silently defaults to `0` (`PAYMENT`), causing silent feature corruption.
- **Recommended Remedy:**
  ```python
  out["type_code"] = df["type"].astype(str).str.upper().map(TX_TYPES).fillna(0).astype(int)
  ```

---

### Finding 1.2: Missing Balance Imputation & Null Handling
- **Scalar Path (`tx_features:49-57`):**
  Intelligently derives missing balances as a clean financial ledger would:
  ```python
  old_o = tx.get("oldbalanceOrg")
  old_o = amount if old_o is None else float(old_o)
  new_o = tx.get("newbalanceOrig")
  new_o = max(old_o - amount, 0.0) if new_o is None else float(new_o)
  old_d = tx.get("oldbalanceDest")
  old_d = 0.0 if old_d is None else float(old_d)
  new_d = tx.get("newbalanceDest")
  new_d = old_d + amount if new_d is None else float(new_d)
  ```
- **Frame Path (`tx_features_frame:86-87`):**
  ```python
  for c in ["amount", "oldbalanceOrg", "newbalanceOrig", "oldbalanceDest", "newbalanceDest", "geo_shift_km"]:
      out[c] = df[c].astype(float)
  ```
  If `df` lacks these columns or contains `None`/`np.nan`, `astype(float)` either crashes with a `KeyError` or preserves `NaN`. This cascades into `orig_balance_err` and `dest_balance_err` becoming `NaN`, leading to silent tree path degeneration in XGBoost.
- **Recommended Remedy:**
  Mirror the imputation logic across the Series:
  ```python
  amount = df["amount"].astype(float)
  out["amount"] = amount
  
  old_o = df["oldbalanceOrg"].astype(float) if "oldbalanceOrg" in df.columns else amount
  old_o = old_o.fillna(amount)
  out["oldbalanceOrg"] = old_o
  
  new_o = df["newbalanceOrig"].astype(float) if "newbalanceOrig" in df.columns else (old_o - amount).clip(lower=0.0)
  new_o = new_o.fillna((old_o - amount).clip(lower=0.0))
  out["newbalanceOrig"] = new_o

  old_d = df["oldbalanceDest"].astype(float) if "oldbalanceDest" in df.columns else 0.0
  old_d = old_d.fillna(0.0)
  out["oldbalanceDest"] = old_d

  new_d = df["newbalanceDest"].astype(float) if "newbalanceDest" in df.columns else (old_d + amount)
  new_d = new_d.fillna(old_d + amount)
  out["newbalanceDest"] = new_d
  ```

---

### Finding 1.3: Unsafe Column Indexing for Optional Context Fields
- **Scalar Path (`tx_features:68-72`):**
  Safely uses `.get()` with defaults:
  ```python
  "geo_shift_km": float(tx.get("geo_shift_km", 0.0)),
  "new_device": int(tx.get("new_device", 0)),
  "merchant_code": MERCHANT_CODES.get(str(tx.get("merchant_category", "p2p")), 0),
  "in_disaster_zone": int(tx.get("in_disaster_zone", 0)),
  "severity_tier": int(tx.get("severity_tier", 0)),
  ```
- **Frame Path (`tx_features_frame:86-93`):**
  Direct column indexing raises `KeyError` if any optional column is omitted from a batch inference DataFrame:
  ```python
  out["new_device"] = df["new_device"].astype(int)  # KeyError if 'new_device' not in df
  ```
- **Recommended Remedy:**
  Use `.get()` or check column membership before casting:
  ```python
  out["geo_shift_km"] = df["geo_shift_km"].astype(float) if "geo_shift_km" in df.columns else 0.0
  out["hour"] = df["hour"].astype(int) if "hour" in df.columns else 12
  out["is_night"] = ((out["hour"] >= 22) | (out["hour"] < 6)).astype(int)
  out["new_device"] = df["new_device"].astype(int) if "new_device" in df.columns else 0
  
  m_cat = df["merchant_category"].astype(str) if "merchant_category" in df.columns else "p2p"
  out["merchant_code"] = m_cat.map(MERCHANT_CODES).fillna(0).astype(int)
  
  out["in_disaster_zone"] = df["in_disaster_zone"].astype(int) if "in_disaster_zone" in df.columns else 0
  out["severity_tier"] = df["severity_tier"].astype(int) if "severity_tier" in df.columns else 0
  ```

---

## 2. Proposed Parity Unit Test (For `tests/test_features.py`)

Chezhil can add this test directly to ensure strict scalar-to-frame parity:

```python
import pandas as pd
import pytest
from data.features import tx_features, tx_features_frame, MODEL_A_FEATURES

def test_tx_features_scalar_vs_frame_parity():
    test_cases = [
        # Case 1: Standard transaction with lowercase type
        {
            "step": 1,
            "type": "transfer",
            "amount": 25000.0,
            "oldbalanceOrg": 50000.0,
            "newbalanceOrig": 25000.0,
            "oldbalanceDest": 1000.0,
            "newbalanceDest": 26000.0,
            "hour": 23,
            "geo_shift_km": 42.5,
            "new_device": 1,
            "merchant_category": "clinic",
            "in_disaster_zone": 1,
            "severity_tier": 3,
        },
        # Case 2: Minimal transaction with missing balances and optional columns omitted
        {
            "type": "PAYMENT",
            "amount": 3500.0,
            "hour": 2,
        },
        # Case 3: Peacetime grocery with 0 balance
        {
            "type": "CASH_OUT",
            "amount": 1200.0,
            "oldbalanceOrg": 1200.0,
            "newbalanceOrig": 0.0,
            "hour": 14,
            "merchant_category": "grocery",
        }
    ]

    for tc in test_cases:
        scalar_out = tx_features(tc)
        frame_out = tx_features_frame(pd.DataFrame([tc])).iloc[0].to_dict()

        for feat in MODEL_A_FEATURES:
            assert feat in scalar_out, f"Missing {feat} in scalar output"
            assert feat in frame_out, f"Missing {feat} in frame output"
            val_s = scalar_out[feat]
            val_f = frame_out[feat]
            assert pytest.approx(val_s, 1e-5) == val_f, (
                f"Mismatch in feature '{feat}': scalar={val_s} vs frame={val_f} for input {tc}"
            )
```

---

## 3. Impact Assessment
- **Frontend / Client:** Client only sends payment columns (`amount`, `type`, `oldbalanceOrg`, etc.) to `/api/v1/evaluate`. The API server uses `tx_features` to compute the feature vector for XGBoost.
- **Model Training:** Offline training pipelines using `tx_features_frame` will now be 100% mathematically aligned with online serving, preventing subtle distribution drift.
