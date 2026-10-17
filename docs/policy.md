# Standard Bank Operations: Disaster Relief & Emergency Payments Policy (DRP-2026)
**Policy ID:** DRP-POLICY-REV-2026.04  
**Classification:** Operational Policy & Compliance Specification  
**Governing Standard:** Disaster Resilience, Financial Inclusion & Ethical AI Directives  
**Target Environment:** Core Banking Payment Gateways on IBM LinuxONE (`s390x`)  

---

### CLAUSE-01: Displacement Anomaly Recognition
1.1. In geographical areas declared under active disaster state (Tier 3–5 by SDRF, NDRF, OpenFEMA, or State Disaster Management Authorities), banking transactions often present sudden, atypical operational signatures.  
1.2. Nocturnal transaction timing (00:00–05:00 IST), abrupt geographic displacement up to 150 km along designated relief or evacuation corridors, and unrecognised or shared emergency shelter device logins shall be classified as **benign displacement anomalies** provided that counterparty analysis demonstrates zero association with known fraud or mule networks.  
1.3. Automated fraud engines shall not execute immediate account-wide freezes solely on the basis of individual displacement indicators.

---

### CLAUSE-02: Provisional Survival Micro-Stipend (REVIEW State)
2.1. Where predictive anomaly models indicate ambiguous or elevated fraud uncertainty (specifically where split conformal prediction yields a set that is not exactly one label (`{legit, fraud}` or empty) or where net expected societal harm satisfies `|H_F - H_H| < tau`) and syndicate mule risk is low (`P(MuleRing) < theta_mule`), the system must invoke the **REVIEW** state.  
2.2. Under `REVIEW`, the engine shall execute a split-liquidity disbursement:
   - **Immediate Survival Payout:** Liquid release of `min(Amount, Cap_survival)`, where `Cap_survival = ₹3,000`. This ensures that legitimate victims are never left with ₹0 for critical food, fuel, or emergency pharmacy supplies.
   - **Disaster Escrow Allocation:** The remaining balance (`max(0, Amount - ₹3,000)`) shall be isolated into an AES-256-GCM encrypted disaster escrow buffer.

---

### CLAUSE-03: 48-Hour Default-to-Release & One-Tap Appeal
3.1. In alignment with the ethical principle of *in dubio pro cive* (in ambiguity, prioritize human survival), all escrowed funds shall automatically disburse to the recipient after **48 hours** unless an analyst or secondary fraud corroboration explicitly confirms fraudulent intent.  
3.2. Account holders placed under `REVIEW` or `HOLD` within a disaster district shall receive immediate, low-bandwidth notification containing a **One-Tap Appeal** option.  
3.3. Filing an appeal prioritizes the transaction in the Emergency Operations Analyst Queue for immediate human adjudication.

---

### CLAUSE-04: Mule-Ring & Syndicate Override (HOLD State)
4.1. Disaster-zone leniency and provisional micro-stipend disbursements apply strictly to individual disaster victims and benign counterparties.  
4.2. If graph topology metrics or the PyTorch neural network identify high mule centrality (`P(MuleRing) >= theta_mule`), rapid fan-in velocity (>=10 distinct payers funneling into a single payee in 15 minutes), device-farm clustering, or burst draining within 10 minutes of credit, all emergency leniency is immediately revoked.  
4.3. The transaction shall transition to **HOLD** (hard block), funds shall be preserved in the remitter's account, and the recipient account shall be quarantined to protect relief aid pools.

---

### CLAUSE-05: Grounded Policy Parameters (Beta & Stipend Cap)
5.1. Rather than utilizing arbitrary mathematical constants, institutional risk parameters are anchored to published Indian economic and disaster management benchmarks:
   - **Wrongful Freeze Harm Base (`beta = ₹345`):** Grounded in one day of the official notified rural minimum daily wage for Tamil Nadu (₹345/day for unskilled manual work in Tamil Nadu, notified by the Ministry of Rural Development on 30 June 2026 under Section 10 of the VB-G RAM G Act, 2025, effective 1 July 2026; reported by [SCC Online](https://www.scconline.com/blog/post/2026/07/06/state-wise-wage-rates-revised-under-vb-g-ram-g-act/)). This quantifies the economic injury inflicted on a vulnerable citizen when legitimate funds are locked for 24 hours.
   - **Survival Stipend Cap (`Cap_survival = ₹3,000`):** Grounded in 50% of the Tamil Nadu Cyclone Michaung flood-relief cash assistance of ₹6,000 per family (Government Order of the Revenue and Disaster Management Department, December 2023, paid in cash through ration shops; reported by [DT Next](https://www.dtnext.in/news/tamilnadu/tn-issues-go-to-disburse-rs-6000-flood-relief-754265) and [Deccan Herald](https://www.deccanherald.com/india/tamil-nadu/tamil-nadu-cm-stalin-launches-flood-relief-of-rs-6000-to-families-affected-by-cyclone-michaung-2814559)). Half of it is meant to cover the first 48 hours.

---

### CLAUSE-06: Demographic & Income-Band Fairness
6.1. To uphold algorithmic justice and non-discrimination, socio-economic proxies—including historical average monthly balance, credit bureau rating, smartphone device price tier, or rural branch domicile—are strictly excluded as model features.  
6.2. The automated decision engine must undergo continuous fairness auditing across synthetic income bands (<₹15,000, ₹15,000–₹50,000, and >₹50,000). The target is a max/min freeze and review ratio of at most 1.25x across groups; audit results are published as measured, including when the target is not met.

---

### CLAUSE-07: Privacy & Masked AI Explanations
7.1. Where generative foundation models (such as IBM Granite 350M running on LinuxONE) generate plain-English explanations for compliance officers or customer communications, zero Personal Identifiable Information (PII) shall enter the prompt.  
7.2. Only an allow-list of facts may enter the prompt; account, device and transaction identifiers and names are never included, and each prompt is checked for raw identifiers before use.  
7.3. Generative outputs are validated against policy citations retrieved via BM25 ranking before presentation to human operators.

---

### CLAUSE-08: Tamper-Evident Audit Ledger
8.1. Every transactional evaluation, micro-stipend authorization, escrow isolation, and analyst override is recorded in an immutable append-only hash chain.  
8.2. Each block calculates `hash = SHA-256(record || prev_hash)` computed through OpenSSL, which uses the IBM Z Central Processor Assist for Cryptographic Functions (CPACF).  
8.3. Escrow allocation records containing sensitive beneficiary tokens are encrypted at rest with AES-256-GCM. Any modification or truncation of ledger history causes immediate hash verification failure via `/api/v1/ledger/verify`.  

---

### CLAUSE-09: Routine Payments Outside Declared Disaster Zones (RELEASE State)
9.1. Outside a declared disaster zone, a payment is released in full when its expected fraud loss does not exceed the expected harm of blocking a legitimate payer by the HOLD margin `tau`, the recipient carries no mule-ring flag, and the fraud model is certain enough.
9.2. No stipend or escrow applies; the decision and its reasons are recorded in the audit ledger.

---

### CLAUSE-10: Clear Fraud and Account Takeover Block (HOLD State)
10.1. When the expected fraud loss exceeds the expected harm of blocking by at least `tau` (for example, an account takeover draining a balance to a new payee), the payment is held in full, funds remain in the remitter's account, and the case enters the analyst queue with a one-tap appeal.
10.2. Inside a declared disaster zone this harm-based block applies only together with the mule-ring override (CLAUSE-04); otherwise the payment becomes a REVIEW with the survival stipend (CLAUSE-02). A HOLD is never released automatically.
