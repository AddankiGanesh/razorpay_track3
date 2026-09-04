# RevRecover — Master Project Context

> **Razorpay AI Buildathon · Track 03: AI Revenue Recovery**
> Consolidated context from all planning discussions. Read this before building anything.
> **Deadline:** September 5, 2026 (build buffer target: September 2, 2026)
>
> **Canonical technical doc:** `PROJECT_ARCHITECTURE.md` (pipeline, APIs, AI/ML map, v0.8.2 updates)
> **Last updated:** September 1, 2026

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [The Track & Judging Bar](#2-the-track--judging-bar)
3. [Tech Stack Decisions](#3-tech-stack-decisions)
4. [What Razorpay Gives vs What We Build](#4-what-razorpay-gives-vs-what-we-build)
5. [Architecture](#5-architecture)
6. [Detection: How Failures Are Found](#6-detection-how-failures-are-found)
7. [Diagnosis: Static Rules + Dynamic Fallback](#7-diagnosis-static-rules--dynamic-fallback)
8. [AI Role (Honest Breakdown)](#8-ai-role-honest-breakdown)
9. [Twilio vs AI — Who Does What](#9-twilio-vs-ai--who-does-what)
10. [Revenue Leak Categories (7 + Enhancements)](#10-revenue-leak-categories-7--enhancements)
11. [Complete Failure Catalog with Examples](#11-complete-failure-catalog-with-examples)
12. [Edge Cases & Differentiators](#12-edge-cases--differentiators)
13. [Recovery Money Calculation](#13-recovery-money-calculation)
14. [Stopping Rules & Compliance](#14-stopping-rules--compliance)
15. [Synthetic Data Generation](#15-synthetic-data-generation)
16. [Tools: SDK, CLI, MCP](#16-tools-sdk-cli-mcp)
17. [Build Phases](#17-build-phases)
18. [Pitch Narrative for Judges](#18-pitch-narrative-for-judges)
19. [Out of Scope](#19-out-of-scope)
20. [Reference Links](#20-reference-links)

---

## 1. Project Overview

**Project name (working):** RevRecover

**One-liner:** An AI agent that detects revenue at risk across payment failures, checkout abandonments, subscription halts, and overdue invoices — diagnoses root cause using Razorpay's error taxonomy — and executes the right recovery action with compliant stopping rules, Hinglish voice for high-value cases, and a provable audit trail of money recovered.

**Core pipeline:**

```
DETECT → DIAGNOSE → DECIDE → EXECUTE → AUDIT
```

**Design principle:** One shared engine with multiple adapters — not separate bolted-together demos.

---

## 2. The Track & Judging Bar

**Track 03: AI Revenue Recovery**
Tagline: *"Find revenue that's slipping away and win it back."*

**Official description:** Build an agent that detects revenue at risk, determines the right intervention, and executes a bounded recovery workflow: from payment failures and checkout abandonment to overdue receivables.

**Judging bar (exact wording — treat as rubric):**
> "Don't just identify the problem. Show measured money recovered across a batch, with compliant escalation, stopping rules, and an audit trail."

**Official example directions:**
- Payment degradation → root cause → recovery action
- Checkout drop-off recovery
- Failed-subscription recovery
- B2B receivables chaser
- Mandate retry sequencer
- Hinglish voice recovery
- Promise-to-pay tracker

**Submission requirements:**
- Public GitHub repo
- 5-minute pitch video
- Architecture explained
- Application form: [Apply](https://forms.gle/d9r2gvxp8cmoZhon9)

**What judges read first:** repo that runs, 5-min video, what broke at 2 AM and how you fixed it.

---

## 3. Tech Stack Decisions

| Layer | Choice | Why |
|-------|--------|-----|
| Language | **Python 3.11+** | Best AI/LLM ecosystem; fast hackathon velocity |
| API framework | **FastAPI** | Webhooks, async, production-grade |
| Razorpay SDK | **razorpay-python** | Official SDK |
| Database | **SQLite** (dev) → **PostgreSQL** (optional prod) | Audit trail + attribution |
| AI / LLM | **Gemini (preferred) or OpenAI** via `llm_client.py` | Diagnosis fallback, message gen, promise-to-pay NLP, narratives |
| Email | **Resend** | Fast setup, no approval delay |
| SMS + Voice | **Twilio** | Delivery only — not the AI brain |
| Webhook tunnel | **ngrok** | Local dev |
| Dashboard | Simple **HTML/React** | Recovery metrics for judges |
| Demo checkout | **Razorpay Checkout.js** (minimal) | One live click in pitch video — build LAST |

**Not chosen:** Java (`razorpay-java` is useful as reference for error field structure only). Node is viable but Python wins on AI integration.

---

## 4. What Razorpay Gives vs What We Build

| Capability | Razorpay | RevRecover |
|------------|----------|------------|
| Detect payment failed | ✅ `payment.failed` webhook | Listens + correlates multiple events |
| Exact failure reason | ✅ `error_reason` field (114 codes) | Maps reason → intervention |
| Broad fault bucket | ✅ `error_source`, `error_step` | Fallback routing when reason unknown |
| Decide if recoverable | ❌ | Recovery likelihood scoring |
| Pick channel (SMS/email/voice) | ❌ | AI + policy engine |
| Pick timing | ❌ | Immediate / delayed / post-downtime |
| Personalize message (Hinglish) | ❌ | LLM |
| Stop over-nudging | ❌ | Stopping rules (max 3, promise-to-pay) |
| Cross-event reasoning | ❌ | "Failed OTP twice + abandoned → voice" |
| Auto-capture / charge halted invoice | ❌ | Razorpay API execution |
| Prove ₹ recovered | ❌ | Attribution DB + dashboard |

**Key insight:** Razorpay is the thermometer. RevRecover is the doctor.

**Anti-pattern (do NOT build):** `if error_reason == "incorrect_otp": send_email()` — that's a cron job, not a buildathon winner.

---

## 5. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      DETECTION LAYER                             │
│                                                                  │
│  Webhooks: payment.failed, payment.authorized, order.paid,      │
│            subscription.pending, subscription.halted,             │
│            subscription.charged, payment_link.paid/expired,       │
│            payment.downtime.started/resolved                      │
│                                                                  │
│  Cron jobs: checkout abandonment, overdue invoices,               │
│             halted subscription revival, uncaptured payments      │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                      ADAPTER LAYER                               │
│                                                                  │
│  A1: Payment Failure Adapter    (payment.failed)                │
│  A2: Abandonment Adapter        (order timeout, no order.paid)  │
│  A3: Subscription Adapter       (pending / halted)              │
│  A4: B2B Receivables Adapter    (invoice / payment link overdue)│
│  A5: Auto-Capture Adapter       (authorized, not captured)      │
│  A6: Late Auth Adapter          (failed → later authorized)     │
│  A7: Downtime Adapter           (downtime webhooks + failures)  │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                   DIAGNOSIS LAYER                                │
│                                                                  │
│  Layer 1: Known error_reason → REASON_ACTIONS lookup (fast)     │
│  Layer 2: Unknown reason → source + step fallback               │
│  Layer 3: Still unknown → LLM diagnosis from description        │
│  Layer 4: Safe default → 1 soft nudge + flag for review           │
│                                                                  │
│  + Recovery score, cross-event context, downtime correlation    │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                   DECISION LAYER (Policy)                        │
│                                                                  │
│  Should we act? Which channel? When? How many attempts left?    │
│  Stopping rules, promise-to-pay suppression, downtime delays    │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                   EXECUTION LAYER                                │
│                                                                  │
│  Twilio SMS  |  Resend Email  |  Twilio Voice IVR (Hinglish)    │
│  Razorpay API: payment links, capture, invoice charge           │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                   AUDIT TRAIL (Database)                         │
│                                                                  │
│  Every event: detection → diagnosis path → action → outcome     │
│  Attribution: intervention_id → recovered payment_id → ₹ amount │
│  Dashboard: at-risk vs recovered, rate by category                │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. Detection: How Failures Are Found

### Razorpay error structure (from webhook / API)

```json
{
  "status": "failed",
  "method": "card",
  "amount": 49900,
  "error_code": "BAD_REQUEST_ERROR",
  "error_description": "Authentication failed due to incorrect otp",
  "error_source": "customer",
  "error_step": "payment_authentication",
  "error_reason": "incorrect_otp"
}
```

| Field | Level | Purpose |
|-------|-------|---------|
| `error_code` | Very broad | e.g. `BAD_REQUEST_ERROR` |
| `error_source` | Broad bucket | `customer`, `bank`, `gateway`, `issuer_bank`, `business`, `internal` |
| `error_step` | Flow stage | `payment_authentication`, `payment_authorization`, etc. |
| `error_reason` | **Exact failure** | 114 distinct codes — primary routing key |
| `error_description` | Human text | Used for LLM fallback + message context |
| `method` | Payment rail | `card`, `upi`, `netbanking`, `wallet`, etc. |

**Important:** `error_source` is NOT a replacement for `error_reason`. Same source/step can have many different exact failures with different fixes (e.g. three OTP-related reasons under `customer` + `payment_authentication`).

### Detection methods by scenario

| Scenario | Detection method |
|----------|------------------|
| Payment failure | `payment.failed` webhook |
| Checkout abandonment | Cron: order created, no `order.paid` after N minutes |
| Subscription pending | `subscription.pending` webhook |
| Subscription halted | `subscription.halted` webhook |
| Overdue B2B invoice | Cron: `status != paid` and past `expire_by` |
| Uncaptured authorized | `payment.authorized` + no capture within 2 min |
| Late authorisation | `payment.failed` then later `payment.authorized` |
| Bank downtime | `payment.downtime.started` / `.resolved` webhooks |
| Partial invoice payment | `invoice.status = partially_paid` |
| Expired payment link | `payment_link.expired` webhook |

### Key webhooks to subscribe

`payment.failed`, `payment.authorized`, `payment.captured`, `order.paid`, `subscription.pending`, `subscription.halted`, `subscription.charged`, `payment_link.paid`, `payment_link.expired`, `payment.downtime.started`, `payment.downtime.resolved`

---

## 7. Diagnosis: Static Rules + Dynamic Fallback

### Why hybrid (not 100% static or 100% LLM)

- **Known reasons (90%+):** Rule lookup — fast, reliable, cheap, demo-safe
- **Unknown/new reasons:** Dynamic fallback — system never breaks
- **Message text:** Always LLM-personalized — even for known rules

### Layer 1 — Known rule lookup

```python
exact_reason = payment["error_reason"]  # e.g. "incorrect_otp"

if exact_reason in REASON_ACTIONS:
    return {"path": "known_rule", "action": REASON_ACTIONS[exact_reason], "confidence": 0.95}
```

`REASON_ACTIONS` loaded from official 114-reason Excel:
`https://razorpay.com/docs/build/browser/assets/images/payments_error_reasons.xlsx`
(local copy: `payments_error_reasons.xlsx`)

### Layer 2 — Source + step fallback (unknown reason)

```python
FALLBACK_BY_SOURCE_STEP = {
    ("customer", "payment_authentication"): {"action": "retry_with_guidance", "channel": ["sms"]},
    ("bank", "payment_authorization"):       {"action": "delay_retry", "check_downtime": True},
    ("gateway", "payment_authorization"):    {"action": "delay_retry", "check_downtime": True},
}
```

### Layer 3 — LLM diagnosis (truly unknown)

Input: `error_reason`, `error_source`, `error_step`, `error_description`, `method`, `amount`
Output JSON: `fault_party`, `recoverable`, `action`, `channel`, `urgency`, `rationale`

### Layer 4 — Safe default

One soft nudge + payment link. Flag `unknown_reason` in dashboard for human review.

### REASON_GROUPS (dashboard only — static, we define)

```python
REASON_GROUPS = {
    "otp_issues":       ["incorrect_otp", "otp_expired", "otp_attempts_exceeded"],
    "funds_issues":     ["insufficient_funds"],
    "bank_outage":      ["bank_technical_error", "gateway_technical_error", "bank_not_available"],
    "card_issues":      ["card_expired", "card_declined", "card_disabled_for_online_payments"],
    "upi_issues":       ["invalid_vpa", "payment_collect_request_expired", "vpa_resolution_failed"],
    "fraud_declines":   ["payment_risk_check_failed"],
    "mandate_issues":   ["debit_declined", "reqauth_mandate_not_acknowledged"],
    "verification":     ["bank_account_validation_failed", "verification_failed", "invalid_device"],
    "abandonment":      ["payment_cancelled", "payment_timed_out"],
}
# New reasons → "uncategorized" until manually added. Recovery still works via fallback.
```

### Self-improving policy (pitch point)

Unknown reasons logged → dashboard shows frequency → promote to `REASON_ACTIONS` after review → next occurrence uses fast rule path.

---

## 8. AI Role (Honest Breakdown)

### Three layers (rules + ML + LLM)

| Layer | What | Example |
|-------|------|---------|
| **Rules** | Known `error_reason` → playbook; stopping rules; downtime DELAYED | `incorrect_otp` → urgent SMS; bank outage → no nudge |
| **Classical ML** | sklearn logistic regression on intervention outcomes | Score 72 vs 28 for chase vs STOP — **not** an LLM |
| **LLM (optional)** | Gemini/OpenAI when configured | Parse `"I will pay next Friday"`; rewrite SMS copy |

**Judge line:** Rules diagnose and enforce compliance; ML scores ROI; Gemini optionally personalizes and parses — always with regex/rule fallbacks.

### Capability map

| AI capability | What it does | Example |
|---------------|--------------|---------|
| Recovery scoring (ML + heuristic) | Prioritize high-probability recoveries | OTP fail = chase; cancelled = 1 nudge max |
| Channel selection | SMS vs email vs voice | ₹50k B2B invoice → voice on day 7 |
| Timing optimization | When to nudge | Bank downtime → DELAYED; insufficient funds → 10 AM next day |
| Message personalization (LLM) | Hinglish, amount-specific | "Aapka ₹499 ka payment OTP galat hone se fail hua" |
| Promise-to-pay NLP | Parse customer replies | `Friday tak pay karunga` or `next Friday` → suppress until date |
| Cross-event reasoning | Multi-signal diagnosis | 2 OTP fails + abandon → suggest UPI + voice |
| Unknown reason diagnosis (LLM) | LLM fallback | New reason not in Excel → `llm_diagnosis` path |
| Voice script | Contextual IVR text | Halted subscription script — **templated** in `voice.py`, not LLM-generated |
| Leakage narrative (LLM) | Report insights | UPI evening peak story in leakage report |

**AI does NOT:** replace Razorpay webhooks for detection, replace Twilio for delivery, or auto-execute payments without consent flows.

### Promise-to-pay UI note (v0.8.2)

- Record promises on **Case history** tab only (voice case → journey panel).
- Parser: regex (Hinglish + English weekdays, `next Friday`, `will pay on Friday`) then optional Gemini.
- API returns `parsed_by` for audit (`regex_next_weekday`, `gemini`, `no_llm_key`, etc.).
- Bug fixed: duplicate HTML `id` caused wrong textarea to be read — now `data-promise-input` + `getPromiseInputEl()`.

### DELAYED vs STOPPED vs WATCHING

| Status | Meaning |
|--------|---------|
| **DELAYED** | Outage active — intervention queued, no customer message yet |
| **STOPPED** | Policy block — max nudges, low score, or promise suppression |
| **WATCHING** | Late auth / pending — monitor only, no customer spam |

---

## 9. Twilio vs AI — Who Does What

```
OUR PYTHON BACKEND (brain)          TWILIO (delivery)
─────────────────────────          ─────────────────
Read webhook                       Send SMS
Score recovery likelihood          Place voice call
Pick channel + timing              Play TTS audio (Hinglish script we write)
Generate message (LLM)             Gather DTMF ("Press 1 to retry")
Stopping rules
Attribution / ₹ tracking
Razorpay API calls
```

### Voice approach (recommended for buildathon)

**Option A — Scripted IVR (build this):**
1. Our LLM generates Hinglish script from `error_reason` + amount
2. Twilio places call, speaks script via TTS, `<Gather>` for keypress
3. Press 1 → our webhook sends payment link SMS via Twilio

**Option B — Conversational voice (only if time permits):**
Vapi / Bland / Retell / Twilio ConversationRelay + LLM. Higher wow factor, higher demo risk.

**Reserve voice for:** halted subscriptions, B2B final escalation, high-value multi-failure abandonments.

---

## 10. Revenue Leak Categories (7 + Enhancements)

### Core 7 categories

| # | Category | Trigger | Recovery type | Build priority |
|---|----------|---------|---------------|----------------|
| 1 | Payment failure (single txn) | `payment.failed` | Customer or system | **Primary** |
| 2 | Checkout abandonment | Order created, no `order.paid` | Customer | **Primary** |
| 3 | Subscription / mandate failure | `subscription.pending` → `halted` | Customer + API | **Primary** |
| 4 | Overdue B2B receivables | Invoice/Payment Link past due | Customer + voice | **Primary** |
| 5 | Authorized-but-not-captured | `payment.authorized`, capture missed | Autonomous | **Bonus — high differentiator** |
| 6 | Suspense / reconciliation mismatch | Debited, not reflected | Autonomous flag | Document / stub |
| 7 | Suboptimal routing | Repeated gateway/BIN failures | Merchant insight | Document / stub |

### Additional enhancements (added in architecture discussions)

| # | Enhancement | Trigger | Why it matters |
|---|-------------|---------|----------------|
| 8 | **Late authorisation** | `payment.failed` then `payment.authorized` days later | Customer charged but merchant thinks it failed |
| 9 | **Partial invoice payment** | `partially_paid` status | Recover remainder, not just full invoice |
| 10 | **Expired payment link regeneration** | `payment_link.expired` | Auto-issue fresh link |
| 11 | **Downtime-aware retry pausing** | `payment.downtime.*` + bank failures | Don't retry during active outage |
| 12 | **Payment pending / don't false-alarm** | `payment_pending` reason | Wait before nudging — may become late auth |
| 13 | **Capture failed auto-retry** | `capture_failed` reason | Retry capture API with backoff |
| 14 | **Repeat failure pattern detection** | Same customer, 3+ failures in 7 days | Escalate channel or suggest method switch |
| 15 | **Recovery likelihood scoring** | All failures | Don't waste nudges on low-probability cases |
| 16 | **Self-improving reason registry** | Unknown `error_reason` logged | Promote to rules after review |
| 17 | **Multi-payment attempt dedup** | Multiple `payment.failed` on same order | One coordinated recovery, not 3 separate blasts |

### Build scope

| Bundle | Categories | Notes |
|--------|------------|-------|
| **Bundle A (primary)** | #1, #2, #3, #4 | One engine, four adapters — mirrors track language |
| **Bundle B (bonus)** | #5, #8 | Cleanest provable ₹ recovered stories |
| **Documented** | #6, #7, #12, #16 | Architecture stub + pitch "future work" |

---

## 11. Complete Failure Catalog with Examples

### GROUP A — One-Time Checkout Failures

| ID | Scenario | Simple example | Detect (`error_reason` or method) | Smart recovery | Naive recovery (avoid) |
|----|----------|----------------|-------------------------------------|----------------|------------------------|
| A1 | Wrong OTP | Rahul enters wrong OTP on ₹499 card payment | `incorrect_otp` | SMS in 15 min: retry with new OTP link | Generic "payment failed" |
| A2 | OTP expired | Customer waited too long | `otp_expired` | Immediate SMS — time-sensitive | Same as A1 |
| A3 | OTP attempts exceeded | 3 wrong OTPs, card blocked | `otp_attempts_exceeded` | Suggest UPI — do NOT retry same card | "Retry with same card" |
| A4 | Insufficient funds | ₹200 balance, ₹499 payment | `insufficient_funds` | SMS next morning 10 AM | Immediate spam |
| A5 | Customer cancelled | Pressed back button | `payment_cancelled` | 1 soft email after 2hr, low priority | 3 aggressive nudges |
| A6 | Payment timed out | 10 min checkout limit exceeded | `payment_timed_out` | Urgency nudge: complete in 2 min | Generic retry |
| A7 | Card expired / disabled | Old card or online off | `card_expired`, `card_disabled_for_online_payments` | Suggest new card or UPI | Retry same card |
| A8 | Bank declined (generic) | Bank said no, reason unclear | `card_declined`, `payment_failed` | Alternate card or UPI | Blame customer |
| A9 | Fraud-flagged decline | Bank security block | `payment_risk_check_failed` | Different method — never same card | Retry same card |
| A10 | Bank/gateway downtime | HDFC netbanking down | `bank_technical_error` + Downtime API | Delay retry until outage clears | Immediate retry during outage |
| A11 | Invalid UPI VPA | Typo in UPI ID | `invalid_vpa` | "Check UPI ID and retry" | Generic fail message |
| A12 | UPI collect expired | Didn't approve in 10 min | `payment_collect_request_expired` | Send new collect request | Give up |
| A13 | UPI device not bound | UPI setup incomplete | `invalid_device` | Educational: complete UPI binding first | Retry blindly |
| A14 | Wrong linked bank (UPI recurring) | Paid from different account | `credit_failed` | Use registered account | Retry same way |
| A15 | Below minimum amount | ₹5 payment, fees too high | `amount_less_than_minimum_amount` | Merchant alert to fix catalog | Customer nudge (wrong target) |
| A16 | Incorrect CVV | Wrong CVV entered | `incorrect_cvv` | Retry with correct CVV; mention saved-card option | Generic fail |
| A17 | Transaction limit exceeded | Daily card limit hit | `transaction_limit_exceeded` | Different card or UPI | Retry same card |
| A18 | Invalid mobile (wallet) | Unregistered wallet number | `invalid_mobile_number` | Use registered number | Generic retry |
| A19 | Card not enrolled for online | Card not activated | `card_not_enrolled` | Guide to enable online transactions | Retry immediately |
| A20 | Maker-checker pending (B2B) | Corp payment needs approval | `payment_pending_approval` | Alert internal approver, not customer | Customer nudge |

### GROUP B — Checkout Abandonment (no failure webhook)

| ID | Scenario | Simple example | Detect | Smart recovery |
|----|----------|----------------|--------|----------------|
| B1 | Abandoned before payment attempt | Added to cart, left — no payment tried | Order + 30 min, zero payment attempts | Soft "cart waiting" email — no failure mention |
| B2 | Abandoned after failure | Card OTP failed, left angry | `payment.failed` then 30 min silence | Reference specific failure: "OTP issue? Try UPI" |
| B3 | Abandoned after multiple failures | Failed 2-3 times, gave up | 2+ failures on same order, silence | Hinglish voice call — high intent signal |

### GROUP C — Subscription / Auto-Payment

| ID | Scenario | Simple example | Detect | Smart recovery |
|----|----------|----------------|--------|----------------|
| C1 | First charge fails (pending) | ₹199/month sub, Day 1 fails | `subscription.pending` | Immediate SMS — don't wait for T+1,2,3 retries |
| C2 | All retries exhausted (halted) | 3 days failed → halted | `subscription.halted` | Voice call + revival job: manual invoice charge if card updated |
| C3 | Mandate cancelled from bank app | Customer revoked eMandate | `debit_declined`, mandate errors | New registration link |
| C4 | Card expired mid-subscription | Card valid at signup, expired at renewal | `card_expired` on charge | Proactive card-update link before next cycle |
| C5 | Insufficient balance on auto-debit | Salary not credited yet | `insufficient_funds` on subscription charge | SMS after 2 days (salary window) + manual charge option |

**Critical halted-subscription fact (from Razorpay docs):**
After `halted`, invoices keep generating but are **never auto-charged again** even if customer updates card. Merchant must manually charge via API. This is silent revenue bleed — key differentiator.

**Do NOT rebuild Razorpay's T+1,2,3 retry loop** — build value AROUND it with earlier proactive intervention.

### GROUP D — B2B / Invoices / Payment Links

| ID | Scenario | Simple example | Detect | Smart recovery |
|----|----------|----------------|--------|----------------|
| D1 | Invoice due in 3 days | ₹25,000 B2B, approaching expiry | Cron on `expire_by` | Tier 1 soft email |
| D2 | Invoice overdue | Past due date | `status = expired` or past `expire_by` | Tier 2 SMS + firmer email |
| D3 | Partial payment | Paid ₹10k of ₹25k | `partially_paid` | Nudge for ₹15k remainder |
| D4 | Promise-to-pay | "Friday tak pay karunga" | NLP on email/SMS reply | Suppress reminders until Friday; escalate if missed |
| D5 | Payment link expired | Link opened on day 8 of 7 | `payment_link.expired` | Auto-regenerate + SMS new link |
| D6 | Final escalation | 2 reminders ignored | Tier 3 trigger | Hinglish voice + optional early-payment discount |

### GROUP E — System / Operational Leaks (autonomous)

| ID | Scenario | Simple example | Detect | Smart recovery |
|----|----------|----------------|--------|----------------|
| E1 | Authorized not captured | Paid, merchant forgot capture → auto-refund | `payment.authorized` + no capture in 2 min | Auto-capture API — zero customer action |
| E2 | Late authorisation | "Failed" on screen but bank debited 6hr later | `payment.failed` → later `payment.authorized` | Auto-capture + fulfilment trigger |
| E3 | Payment pending (pre-late-auth) | Stuck in pending | `payment_pending` | Wait 30 min — don't false-alarm customer |
| E4 | Capture failed | Bank authorized, capture API errored | `capture_failed` | Auto-retry capture 3x with backoff |

### GROUP F — Downtime & Routing (cross-cutting)

| ID | Scenario | Simple example | Detect | Smart recovery |
|----|----------|----------------|--------|----------------|
| F1 | Active downtime + failure | Payment fails during HDFC outage | `bank_technical_error` + `payment.downtime.started` | Pause retries; resume on `.resolved` |
| F2 | Repeated BIN/gateway failures | 50 HDFC failures today | Pattern on same bank/gateway in batch | Merchant alert: multi-terminal routing |
| F3 | Post-downtime recovery burst | Outage just resolved | `payment.downtime.resolved` | Retry queued failures for that bank |

---

## 12. Edge Cases & Differentiators

### Edge cases most teams will miss

1. **Halted subscription silent bleed** — invoices generate, never auto-charge after halt
2. **Authorized-not-captured** — provable autonomous ₹ recovery
3. **Late authorisation** — customer thinks failed, money actually debited
4. **Downtime-aware delays** — retrying during outage wastes nudges and annoys customers
5. **OTP attempts exceeded vs incorrect OTP** — same "category", opposite actions
6. **Fraud decline** — looks like payment failure but must NOT retry same card (not deep fraud logic — that's Track 02)
7. **Abandonment after specific failure** — nudge must reference actual `error_reason`, not generic cart email
8. **Partial payments** — recover remainder, not re-request full amount
9. **Promise-to-pay** — compliant suppression of reminders
10. **Multiple failures same order** — one coordinated recovery, not 3 separate blasts
11. **Payment pending** — don't nudge before late auth resolves
12. **Unknown/new error_reason** — LLM fallback + safe default, never crash
13. **Promise input on wrong tab** — duplicate DOM ids silently swapped user text (fixed v0.8.2)

### Payment rails (failures differ by method)

Cards, UPI, Netbanking, Wallets, EMI, Pay Later, eMandate/NACH — each has distinct `source`/`step`/`reason` values per Razorpay docs.

Card sources: `customer`, `business`, `internal`, `gateway`, `issuer_bank`

---

## 13. Recovery Money Calculation

### Definitions

```
₹ At Risk     = sum of failed / abandoned / uncaptured / halted amounts in batch
₹ Recovered   = sum that became paid/captured AFTER our intervention
Recovery Rate = (Recovered / At Risk) × 100
```

### Attribution model

```
Failed payment pay_ABC (₹499 at risk)
    → Intervention #101 (SMS with payment link)
    → Customer pays pay_XYZ (₹499 captured)
    → ₹499 recovered, attributed to intervention #101
```

### What counts as "recovered" per scenario

| Scenario | Recovered when |
|----------|----------------|
| Checkout failure | `payment.captured` on same order after nudge |
| Abandonment | `order.paid` after nudge |
| Subscription pending | `subscription.charged` after proactive nudge |
| Subscription halted | Manual `invoice.charge()` succeeds after revival job |
| Uncaptured | `payment.captured` by auto-capture agent |
| Late auth | `payment.captured` before auto-refund window |
| B2B invoice | `invoice.paid` or `payment_link.paid` after reminder |
| Partial payment | Remaining amount paid after remainder nudge |

### Example batch dashboard

```
87 revenue-at-risk cases | ₹1,42,300 at risk | ₹89,450 recovered | 62.8% rate

By category:
  Payment failures:     21/34 recovered (61.8%)
  Abandonments:          9/18 recovered (50.0%)
  Subscriptions:         7/12 recovered (58.3%)
  B2B invoices:          8/15 recovered (53.3%)
  Auto-capture:          5/5  recovered (100%)
  Late auth:             2/3  recovered (66.7%)
```

### Audit log fields (every action)

`event_id`, `timestamp`, `category`, `detection_source`, `error_reason`, `diagnosis_path` (known_rule / fallback / llm / default), `action_taken`, `channel`, `intervention_id`, `outcome`, `amount_at_risk`, `amount_recovered`, `customer_contact`

---

## 14. Stopping Rules & Compliance

Borrowed from Razorpay's own product decisions (shows deep docs research):

| Rule | Implementation |
|------|----------------|
| Max 3 automated reminders | Match Payment Links reminder cap |
| Send windows | Prefer 11 AM–12 PM and 3 PM–5 PM for SMS (Razorpay convention) |
| Bank downtime | No retries during active outage |
| Fraud decline | No retry on same card |
| OTP exceeded | No retry same card — alternate method only |
| Cancelled payment | Max 1 soft nudge (low recovery probability) |
| Promise-to-pay | Suppress all nudges until promised date |
| Voice calls | Max 1 per subscription cycle / invoice escalation |
| Low recovery score | Skip aggressive channels |

---

## 15. Synthetic Data Generation

**What it is:** A Python script that programmatically creates 50–100+ test-mode orders, payments, subscriptions, and invoices via Razorpay API — with varied failure reasons and timings. NOT fake/mock data — real Razorpay test objects.

**Why:** Judges want "measured recovery across a batch." You can't wait for 50 real customers to fail.

**What it creates:**
- Orders with simulated card/UPI failures (test cards)
- Subscriptions that enter `pending` / `halted`
- Invoices with past `expire_by`
- Authorized payments where capture is deliberately skipped
- Abandoned orders (created, no payment attempt)

**What it does NOT replace:** Webhook receiver must still process real events. Synthetic generator seeds the batch; webhooks drive the pipeline.

**Do NOT build:** Full e-commerce storefront. Razorpay isn't judging web design.

**Optional polish (build LAST):** One bare Checkout.js HTML page for live demo click in pitch video.

---

## 16. Tools: SDK, CLI, MCP

### Razorpay Python SDK
Primary integration for webhooks, capture, payment links, invoice charge.

### Razorpay CLI
Install: `scoop install razorpay` (Windows) or curl install script (macOS/Linux).
Docs: https://razorpay.com/docs/api/install-cli/
Use for: quick manual API testing during dev, CI scripts.

### Razorpay MCP Server
Docs: https://razorpay.com/docs/mcp-server/
GitHub: https://github.com/razorpay/razorpay-mcp-server

**Role:** Dev accelerator in Cursor/Claude — NOT the product centerpiece.
- Remote: `npx mcp-remote https://mcp.razorpay.com/mcp`
- 35+ tools: create_order, capture_payment, fetch payments, payment links, etc.

### Test mode setup
- Dashboard: https://dashboard.razorpay.com/app/dashboard (toggle Test Mode)
- API keys: Account & Settings → API Keys
- Webhook testing: ngrok → local FastAPI server
- No full KYC needed for test mode

---

## 17. Build Phases

### Phase 1 — Foundation (Days 1–2)
- [ ] Razorpay test keys + webhook endpoint (FastAPI + ngrok)
- [ ] Project scaffold (`RevRecover/`)
- [ ] SQLite audit schema + attribution tables
- [ ] Load 114-reason Excel into `REASON_ACTIONS`
- [ ] Synthetic data generator (50+ scenarios)

### Phase 2 — Core Pipeline (Days 3–4)
- [ ] Webhook receiver (all key events)
- [ ] Adapters: payment failure, abandonment, subscription, B2B
- [ ] 3-layer diagnosis (rule → fallback → LLM → default)
- [ ] Decision policy + stopping rules
- [ ] Email (Resend) + SMS (Twilio) execution

### Phase 3 — Standout Features (Days 5–6)
- [ ] Auto-capture adapter (#5)
- [ ] Late auth handler (#8)
- [ ] Halted subscription revival job
- [ ] Hinglish voice IVR (Twilio)
- [ ] Downtime-aware retry pausing
- [ ] Promise-to-pay NLP
- [ ] Partial payment + expired link regeneration

### Phase 4 — Demo & Pitch (Days 7–8)
- [ ] Recovery metrics dashboard
- [ ] Full batch test → real ₹ numbers
- [ ] Minimal Checkout.js page (optional)
- [ ] 5-minute pitch video
- [ ] README + architecture diagram

### Phase 5 — Buffer (Day 9)
- [ ] Polish, fixes only — no new features

---

## 18. Pitch Narrative for Judges

**Opening:** "Revenue doesn't vanish in one step. It leaks through payment failures, abandoned carts, halted subscriptions, and uncaptured authorizations. RevRecover closes that loop."

**Architecture story:** One engine, multiple adapters. Detect → Diagnose → Decide → Execute → Audit.

**Differentiators:**
1. Root-cause routing on 114 Razorpay reason codes — not blanket retry
2. Auto-capture + late auth — autonomous ₹ recovery nobody else builds
3. Halted subscription revival — silent bleed Razorpay docs describe but merchants ignore
4. Hinglish voice for high-value cases — track-endorsed, high effort
5. Dynamic fallback for unknown errors — self-improving policy
6. Measured batch recovery with full audit trail

**Demo flow:**
1. Show dashboard: ₹X at risk → ₹Y recovered
2. Live webhook: payment fails → agent diagnoses → SMS sent
3. Voice call demo for halted subscription
4. Auto-capture saving an authorized payment
5. Audit trail: every decision logged

**What broke at 2 AM (have a real story ready):** webhook signature validation, ngrok timeout, Twilio trial number limits, etc.

---

## 19. Out of Scope

- **Track 02 territory:** Fraud detection, chargeback response, return-risk scoring, abuse rings
- **Deep fraud logic:** Route away from fraud declines; don't build fraud ML
- **Full e-commerce storefront**
- **Rebuilding Razorpay's subscription retry loop** (T+1,2,3)
- **Real WhatsApp Business API** (mock/log unless Meta approval obtained)
- **100% LLM diagnosis** (unreliable for demo — use hybrid)

---

## 20. Reference Links

| Resource | URL |
|----------|-----|
| Buildathon track page | https://razorpay.com/buildathon/ |
| Error reasons (overview) | https://razorpay.com/docs/errors/ |
| Error reasons Excel (114 codes) | https://razorpay.com/docs/build/browser/assets/images/payments_error_reasons.xlsx |
| Card error codes | https://razorpay.com/docs/errors/payments/cards/ |
| UPI error codes | https://razorpay.com/docs/errors/payments/upi/ |
| Payment method error params | https://razorpay.com/docs/errors/payments/payment-methods-error-parameters/ |
| Payments webhooks | https://razorpay.com/docs/webhooks/payments/ |
| Subscription retries | https://razorpay.com/docs/payments/subscriptions/payment-retries/ |
| Subscription states | https://razorpay.com/docs/payments/subscriptions/states/ |
| Late authorisation | https://razorpay.com/docs/payments/payments/late-authorisation/ |
| Handle late auth | https://razorpay.com/docs/payments/payments/late-authorisation/handle/ |
| Downtime API | https://razorpay.com/docs/api/payments/downtime/ |
| Payment link reminders | https://razorpay.com/docs/payments/payment-links/reminders/ |
| Invoices API | https://razorpay.com/docs/api/payments/invoices/ |
| Sandbox setup | https://razorpay.com/docs/api/sandbox-setup/ |
| Install CLI | https://razorpay.com/docs/api/install-cli/ |
| MCP server docs | https://razorpay.com/docs/mcp-server/ |
| MCP GitHub | https://github.com/razorpay/razorpay-mcp-server |
| Razorpay Java SDK (reference) | https://github.com/razorpay/razorpay-java |
| Dashboard | https://dashboard.razorpay.com/app/dashboard |

---

## Appendix A — Top `error_reason` → Action Quick Reference

| `error_reason` | Fault | Action | Channel | Notes |
|----------------|-------|--------|---------|-------|
| `incorrect_otp` | customer | retry_with_new_otp | sms | 15 min delay |
| `otp_expired` | customer | retry_immediate | sms | Time-sensitive |
| `otp_attempts_exceeded` | customer | suggest_alternate_method | sms | Never same card |
| `insufficient_funds` | customer | retry_delayed | sms | Next morning |
| `payment_cancelled` | customer | soft_nudge_once | email | Low priority |
| `payment_timed_out` | customer | retry_with_urgency | sms | — |
| `card_expired` | customer | suggest_alternate_method | sms | — |
| `card_declined` | bank/customer | suggest_alternate_method | sms | — |
| `payment_risk_check_failed` | bank | suggest_alternate_method | sms | Never same card |
| `bank_technical_error` | bank | delay_retry | email | Check downtime API |
| `gateway_technical_error` | gateway | delay_retry | email | Check downtime API |
| `invalid_vpa` | customer | retry_with_guidance | sms | — |
| `payment_collect_request_expired` | customer | resend_collect | sms | — |
| `invalid_device` | customer | educational_nudge | email | UPI setup |
| `bank_account_validation_failed` | customer | verify_and_retry | email | KYC/verification |
| `capture_failed` | gateway | auto_retry_capture | system | 3x backoff |
| `payment_pending` | bank | wait_and_poll | system | No customer nudge yet |
| `debit_declined` | customer/bank | mandate_re_registration | sms+email | Subscriptions |
| *(unknown)* | — | llm_fallback → safe_default | varies | Log for review |

---

## Appendix B — Notification Channel Priority

| Priority | Channel | Build effort | Notes |
|----------|---------|--------------|-------|
| 1 | Email (Resend) | Hours | Fastest to wire |
| 2 | SMS (Twilio) | Hours | Trial works for test numbers |
| 3 | Voice IVR (Twilio) | 1 day | Standout differentiator |
| 4 | WhatsApp | Mock only | Meta approval too slow for buildathon |

---

*Last updated: August 27, 2026 — consolidates CONTEXT.md planning + full architecture discussions.*
