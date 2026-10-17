# NYAYA: Frequently Asked Questions & Jury Briefing Sheet

---

## 1. Verified Real-World Impact Figures (India Context)

| Indicator | Metric & Grounding | Authoritative Source |
|---|---|---|
| **Disaster Displacements (2024)** | **5.4 million** internal displacements in India in 2024 (highest in 12 years). Floods accounted for two-thirds (~3.6 million); **Assam alone recorded 2.5 million** displaced citizens. | IDMC (Internal Displacement Monitoring Centre), *Global Report on Internal Displacement (GRID 2025)* |
| **Decadal Displacements (2015–2024)** | **32.3 million** cumulative internal displacements in India over 10 years, ranking **3rd highest in the world**. | IDMC *GRID 2025* |
| **Vulnerable Account Infrastructure** | **59.09 crore** Pradhan Mantri Jan Dhan Yojana (PMJDY) accounts as of August 2026. Approximately **78%** are located in rural and semi-urban locations—the exact accounts receiving emergency Direct Benefit Transfers (DBT), relief grants, and wage credits. | Ministry of Finance / Press Information Bureau (PIB) |
| **Unmeasured Harm Thesis** | *"No commercial bank or public agency measures how many innocent disaster victims have their accounts mistakenly frozen at midnight during floods. NYAYA makes this hidden humanitarian harm measurable and preventable."* | NYAYA Core Thesis |
| **Grounded Parameter: $\beta$** | **₹345 / day**: Set to 1 day of the official notified rural daily minimum wage for Tamil Nadu (under the 2026–27 VB-G RAM G / MGNREGS notification; revised from ₹336/day in 2025–26). Represents the economic injury of freezing a family's daily bread. | Ministry of Rural Development, Govt. of India ([https://nrega.nic.in](https://nrega.nic.in)) |
| **Grounded Parameter: Stipend Cap** | **₹3,000**: Grounded in 50% of the Tamil Nadu State Disaster Response Fund (SDRF) Cyclone Michaung emergency flood-relief cash grant (₹6,000 per affected household) for immediate 48-hour household survival. | Government of Tamil Nadu (Disaster Management, [https://tnsdma.tn.gov.in](https://tnsdma.tn.gov.in) G.O. Ms. No. 587) |

---

## 2. The 10 Judge Q&A Rows (Plan v4 §15)

### Q1: Isn't the data synthetic?
**Answer:** Yes, this is transparently disclosed. PaySim (Kaggle) and OpenFEMA disaster declarations are genuine, public datasets. PaySim provides base financial balance dynamics, and OpenFEMA provides historical disaster declarations and severity levels. Individual disaster displacement patterns and adaptive syndicate attacks are generated via a deterministic, reproducible synthetic pipeline (`data/generate.py`). We showcase the algorithmic decision architecture, cost-sensitive tradeoffs, and hardware efficiency on IBM LinuxONE, not fabricated production accuracy claims.

### Q2: Who decides $\alpha, \beta$, and the Survival Stipend Cap? How is harm calculated?
**Answer:** These are institutional policy parameters set by bank risk and compliance committees:
* $\beta = ₹345/\text{day}$ is grounded in the official Tamil Nadu rural minimum daily wage published by the Ministry of Rural Development ([https://nrega.nic.in](https://nrega.nic.in)).
* $\text{Cap}_{\text{survival}} = ₹3,000$ is grounded in 50% of the Tamil Nadu SDRF Cyclone Michaung emergency flood relief cash grant ([https://tnsdma.tn.gov.in](https://tnsdma.tn.gov.in)).
* **Harm Calculation:** The expected societal harm differential is evaluated strictly in Indian Rupees (₹) as:
  $$\Delta H = H_{\text{fraud}} - H_{\text{hold}}$$
  where:
  - $H_{\text{fraud}} = P(\text{Fraud}) \times \text{Amount}$ is the expected loss if a fraudulent payment is released.
  - $H_{\text{hold}} = (1 - P(\text{Fraud})) \times \beta \times e^{\alpha S} \times \text{urgency}(\text{category})$ is the expected harm of blocking a legitimate payer, where $S$ is the disaster severity tier (0 outside a declared zone) and urgency is 1.5 for pharmacy/clinic down to 0.5 for jewellery (`api/policy_defaults.json`).
  - `HOLD` if $P(\text{Mule}) \ge \theta_{\text{mule}}$ or $\Delta H \ge \tau$. With the zone rule on (`zone_hold_needs_mule`), a harm-based HOLD inside a declared zone becomes `REVIEW`, so only the mule override can leave a payer with ₹0.
  - `REVIEW` if not HOLD and (the conformal set is not a single label, or $\Delta H > -\tau_{\text{review}}$) and the amount is above the cap: $\min(\text{Amount}, ₹3,000)$ is paid now and the rest waits in 48-hour escrow.
  - `RELEASE` otherwise (`engine/policy.py`).
Our Policy Console allows bank risk officers to adjust these values dynamically and view the live Pareto frontier.

### Q3: Isn't NYAYA just a set of hard-coded `if-else` rules?
**Answer:** Absolutely not. NYAYA features two learned machine learning models:
1. **Model A (XGBoost):** Anomaly model trained on PaySim balance dynamics and displacement features, calibrated with isotonic regression to ensure mathematically valid probabilities.
2. **Model B (PyTorch MLP):** Trained on 7 recipient graph features to detect mule-ring accounts. It is served on the **IBM Telum NNPA**; at this model size the NNPA is measured slower than the CPU (see Q9), so we claim no speed-up.
3. **Conformal Uncertainty:** Split conformal prediction at 90% coverage generates prediction sets (`{legit}`, `{fraud}`, `{legit, fraud}` or empty). Any set that is not exactly one label signals that the model is unsure and pushes a payment above the stipend cap to `REVIEW`. Rules only exist at the policy layer to enforce legal escrow timelines and appeal guarantees.

### Q4: What if a criminal syndicate adapts their attack strategy?
**Answer:** We explicitly performed an adversarial red-team test against NYAYA testing 3 real-world adaptation tactics:
* **Smurfing:** Spreading transfers across 3× more mule accounts to stay below the fan-in burst threshold.
* **Device Spoofing:** Rotating fresh device fingerprints.
* **Slow Drip:** Delaying forwarding velocity beyond 10 minutes.  
Measured on 6,000 syndicate payments per attack (`artifacts/sim/redteam.json`, shown in Tab 4; detection = HOLD or REVIEW): base 93.8%, smurfing 80.4%, device spoofing 83.5%, slow drip 77.0%. NYAYA weakens against every variant and slow drip is the hardest; more of each attack lands in REVIEW, where only the stipend leaks and the rest waits in escrow for an analyst.

### Q5: Why is IBM LinuxONE / IBM Z essential for this workload?
**Answer:** Three reasons native to enterprise banking:
1. **On-chip AI accelerator:** Model B runs on the IBM Telum on-chip AI accelerator (NNPA) without sending transaction data to an external GPU. At our model size it is measured slower than the CPU (Q9); larger models are where the NNPA is expected to pay off, which we have not measured.
2. **CPACF hardware cryptography:** SHA-256 for the ledger chain and AES-256-GCM for escrow records run through OpenSSL, which uses the CPACF instructions (`msa` CPU feature). Measured throughput is in `docs/evidence/openssl_sha256.txt` and `openssl_aes256gcm.txt` (`deploy/evidence.sh`).
3. **Zero-Trust Enterprise Security:** Red Hat Enterprise Linux running rootless Podman under SELinux Enforcing mode ensures core banking data and proprietary risk models remain strictly isolated.

### Q6: How is user privacy protected when pairing with IBM Granite?
**Answer:** Granite only ever sees an allow-list of facts (decision, amounts, category, severity, scores, top reasons, clause; `explain/masker.py`). Account, device and transaction identifiers are never copied in, and every prompt is checked against raw-identifier patterns before it is sent. Furthermore, IBM Granite runs locally within the enterprise perimeter via llama.cpp on LinuxONE, ensuring zero data egress to public APIs.

### Q7: What about false negatives? Does NYAYA leak fraud to achieve higher availability?
**Answer:** Fraud exposure is strictly bounded. Under `REVIEW`, risk is capped at the ₹3,000 micro-stipend, while the remaining balance sits in secure escrow. Furthermore, our PyTorch mule network enforces an absolute override: any account displaying syndicate fan-in characteristics is blocked immediately (`HOLD`), preventing organized rings from exploiting disaster leniency.

### Q8: How does NYAYA ensure fairness across income brackets?
**Answer:** Displaced citizens in disaster zones often rely on low-cost prepaid phones, public shelters, and have lower average balances. To prevent penalizing poverty, NYAYA explicitly excludes account balance size, credit ratings, or device cost from the anomaly scoring pipeline. We audit freeze and REVIEW rates by synthetic income band after scoring. The 1.25× parity target is **not met**: on legitimate payments the max/min freeze ratio is 1.30 and the REVIEW ratio 1.61 (small counts, so the ratios are noisy; `models/MODEL_CARD.md`). We report it as measured and did not tune the policy to pass it.

### Q9: How do you prove the PyTorch model executed on the Telum NNPA accelerator?
**Answer:** `lscpu` shows the `nnpa` CPU feature, `torch.nnpa.is_available()` is true, and `/api/v1/system` reports `mule_device: nnpa`. `artifacts/bench/throughput.json` (Tab 4) times Model B on CPU and NNPA at batch sizes 1, 100 and 10,000: p50 0.026 vs 0.035 ms, 0.043 vs 0.040 ms, 1.70 vs 4.16 ms. The NNPA is slower except at batch 100, so we claim no speed-up.

### Q10: How would a Tier-1 commercial bank integrate NYAYA?
**Answer:** NYAYA is packaged as a high-performance REST microservice (FastAPI on Podman) designed to run alongside standard ISO 20022 payment engines (e.g., IBM CICS, IMS, z/OS Connect). It receives payment authorization payloads, enriches them with in-memory graph metrics, and returns a tri-state decision (`RELEASE`, `REVIEW`, `HOLD`) along with audit-ready plain-English reasoning. Measured latency is reported by `/api/v1/system` and `deploy/loadtest.py`.

---

## 3. Model Card Summary

- **Model A (Transaction Anomaly):** XGBoost 3.4.1 binary classifier trained on PaySim balance dynamics (`amount`, `oldbalanceOrg`, `newbalanceOrig`, `oldbalanceDest`, `newbalanceDest`) + contextual displacement features. Calibrated with Isotonic Regression (`sklearn.isotonic.IsotonicRegression`) to output true posterior fraud probabilities $P(\text{Fraud})$.
- **Model B (Mule Ring Centrality):** PyTorch 2.11 MLP (7 $\rightarrow$ 32 $\rightarrow$ 16 $\rightarrow$ 1) trained on 60-minute in-memory graph features (`fan_in_15m`, `unique_senders_15m`, `forward_within_10m_ratio`, `account_age_days`, `device_reuse_density`, `shared_subnet_count`, `mci`). Served on the IBM Telum NNPA (measured slower than CPU at this size).
- **Uncertainty Quantification:** Split conformal prediction at $1 - \alpha = 0.90$ coverage. Sets that are not exactly one label (both or empty) count as uncertain.
- **Explainability:** Per-decision Shapley feature attributions computed natively via XGBoost TreeSHAP (`pred_contribs=True`). Counterfactual search over top-3 features identifies minimum perturbations to flip `HOLD` or `REVIEW` to `RELEASE`.
