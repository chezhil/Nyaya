# Disaster Relief & Emergency Payments Policy
**Policy ID:** DRP-POLICY-REV-2026.04  
**Classification:** Operational Policy Specification for IBM LinuxONE Core Banking Engines  

### CLAUSE-01 Displacement Anomaly Recognition
During declared Tier 3–5 disasters (notified by SDRF, NDRF, OpenFEMA, or State Disaster Management Authorities), banking transactions often present sudden, atypical operational signatures. Nocturnal transactions (00:00–05:00 IST), abrupt geographic shifts up to 150 km along designated relief or evacuation corridors, and borrowed-device logins with zero mule-network links shall be treated as benign displacement anomalies rather than account takeovers. Automated fraud engines shall not execute immediate account-wide freezes solely on the basis of individual displacement indicators.

### CLAUSE-02 Provisional Survival Micro-Stipend (REVIEW)
When a transaction inside an active disaster zone has uncertain fraud risk (specifically where split conformal prediction yields a set that is not exactly one label (`{legit, fraud}` or empty) or where net expected societal harm satisfies `|H_F - H_H| < tau`) and syndicate mule risk is low (`P(MuleRing) < theta_mule`), the system must invoke the REVIEW state. Under REVIEW, the engine must execute a split-liquidity disbursement: an immediate liquid survival stipend of up to ₹3,000 (`Cap_survival`) so the victim is never left with ₹0 for food, fuel, or emergency pharmacy supplies, while placing the remaining balance (`Amount - ₹3,000`) into AES-256-GCM encrypted escrow.

### CLAUSE-03 48-Hour Default-to-Release & One-Tap Appeal
In alignment with the ethical principle of *in dubio pro cive* (in ambiguity, prioritize human survival), all escrowed emergency funds automatically release to the beneficiary after 48 hours unless fraud is affirmatively confirmed by an analyst or secondary corroboration. Account holders receiving a REVIEW or HOLD notification within a disaster district have an immediate right to trigger a one-tap urgent appeal routed directly to the priority human analyst queue for accelerated adjudication.

### CLAUSE-04 Mule-Ring & Syndicate Override (HOLD)
Disaster-zone leniency and provisional micro-stipend disbursements apply strictly to individual disaster victims and benign counterparties. If the recipient account exhibits high Mule Centrality Index (`P(MuleRing) >= theta_mule`), rapid fan-in bursts (>=10 distinct senders in 15 minutes), shared device-fingerprint farms, or rapid forwarding within 10 minutes of credit, all disaster-zone leniency is immediately revoked. The transaction is immediately placed on HOLD (hard block), funds are preserved in the remitter's account, and the recipient account is quarantined to protect public relief aid pools.

### CLAUSE-05 Grounded Policy Parameters (Beta & Stipend Cap)
Institutional risk parameters are anchored directly to official Indian economic and disaster management benchmarks rather than arbitrary constants:
- **Wrongful Freeze Harm Base (`beta = ₹345`):** Grounded in one day of the official notified rural minimum daily wage for Tamil Nadu (₹345/day under the 2026–27 VB-G RAM G / MGNREGS notification; revised from ₹336/day in 2025–26, published by the Ministry of Rural Development, Government of India: [https://nrega.nic.in](https://nrega.nic.in)). This reflects the immediate economic shock experienced when sustenance liquidity is frozen.
- **Survival Stipend Cap (`Cap_survival = ₹3,000`):** Grounded in 50% of the Tamil Nadu State Disaster Response Fund (SDRF) Cyclone Michaung flood-relief cash assistance (₹6,000 per family) for immediate 48-hour household survival, notified by the Revenue and Disaster Management Department, Government of Tamil Nadu: [https://tnsdma.tn.gov.in](https://tnsdma.tn.gov.in) (G.O. Ms. No. 587).

### CLAUSE-06 Demographic & Income-Band Fairness
To uphold algorithmic justice and ethical financial inclusion, socio-economic proxies—including historical average balance, credit bureau rating, smartphone device price tier, or rural branch code—are strictly excluded as model features. Freeze and REVIEW rates across income bands (<₹15,000, ₹15,000–₹50,000, and >₹50,000) are audited after scoring against a 1.25x max/min parity target; results are published as measured, including when the target is not met.

### CLAUSE-07 Privacy & Masked AI Explanations
Any generative foundation model (IBM Granite 350M running on LinuxONE) generating plain-English audit cards receives only an allow-list of masked facts. Zero Personal Identifiable Information (PII) shall enter the prompt: account, device and transaction identifiers and names are never included, and each prompt is checked for raw identifiers before use. Outputs are cross-referenced against the cited policy clause retrieved via BM25 ranking.

### CLAUSE-08 Tamper-Evident Audit Ledger
Every automated decision, micro-stipend allocation, escrow lock, and human analyst override is cryptographically linked in an immutable append-only hash chain. Each record calculates `hash = SHA-256(record || prev_hash)` computed through OpenSSL, which uses the IBM Z Central Processor Assist for Cryptographic Functions (CPACF). All escrow records are encrypted at rest with AES-256-GCM, and verification is continuously auditable via `/api/v1/ledger/verify`.
