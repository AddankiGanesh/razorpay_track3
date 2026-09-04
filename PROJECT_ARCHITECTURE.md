# RevRecover — Project Architecture

**AI Revenue Recovery Operator** for Razorpay Buildathon Track 03  
**Stack:** Python 3.11+, FastAPI, SQLAlchemy (SQLite), Razorpay APIs, optional Resend/Twilio/ElevenLabs/Gemini/OpenAI

**Related docs:** `PROJECT_CONTEXT.md` (planning + failure catalog) · `README.md` (run + quick demo) · `DEMO_SCRIPT.md` (2-min judge script) · `CONTEXT.md` (original planning notes)

**Last updated:** September 4, 2026 (v0.8.3 — dashboard charts, port fallback, docs sync)

---

## 1. What this project is

Razorpay tells merchants **money is at risk**. RevRecover answers:

- **How much is realistically recoverable (ERR)?**
- **Which cases should we pursue vs STOP?**
- **What is the ROI per rupee of recovery spend?**

It is **not** a generic “send everyone a payment link” bot. Every failure is scored 0–100, channel cost is estimated, and low-ROI cases are stopped by policy.

### Judge pitch (30 seconds)

> “Razorpay shows money at risk. We show **realistically recoverable revenue (ERR)**, score every case 0–100, pursue only when **ROI > 1**, and **STOP** low-probability customers. Goal: **maximum recovered revenue per rupee of recovery cost** — not maximum reminders.”

---

## 2. Quick start

```bash
cd razorpay
pip install -r requirements.txt
cp .env.example .env   # fill Razorpay keys (required)
python -m app.run      # http://localhost:8000/
```

**Demo flow**

1. Open **/** (unified UI)
2. Click **Seed 2000 ML batch** → trains model on ~1400 intervention outcomes
3. Fire **subscription_halted** with `ganeshsuraj29@gmail.com` (high score) vs `churned@demo.revrecover.test` (STOP)
4. Fire **bank_technical_error** → **DELAYED** (outage — no customer spam until recovery)
5. **Case history** tab → select a **voice** case → journey panel → record promise (`I will pay next Friday` or `Friday tak pay karunga`)
6. Case history → click row → recovery score + journey timeline + `parsed_by` (regex vs Gemini)

---

## 3. High-level architecture

```
Razorpay webhooks / Lab scenarios
        │
        ▼
┌───────────────────┐
│  Detect + Audit   │  audit_events table
└─────────┬─────────┘
          ▼
┌───────────────────┐
│ Diagnosis Engine  │  110+ error reasons → action playbook
└─────────┬─────────┘
          ▼
┌───────────────────┐
│ Customer Context  │  local history + demo personas + Razorpay cache
└─────────┬─────────┘
          ▼
┌───────────────────┐
│ Recovery Score    │  0–100, ERR, ROI, pursue/STOP (+ learn loop boost)
└─────────┬─────────┘
          ▼
┌───────────────────┐
│ Stopping Rules    │  max nudges, soft-nudge-once, post-recovery suppress
└─────────┬─────────┘
          ▼
┌───────────────────┐
│ Execute Recovery  │  payment link, email/SMS, voice, discount, escalation
└─────────┬─────────┘
          ▼
┌───────────────────┐
│ Attribute Success │  order.paid / payment_link.paid (idempotent)
└───────────────────┘
```

### Intelligence layer (dashboard)

| Module | Purpose |
|--------|---------|
| `recovery_economics.py` | ERR, leak funnel, recovery plan buckets |
| `recovery_score.py` | Per-case score, expected recovery, channel cost, ROI |
| `learn_loop.py` | Learn win-rates by reason+action → score adjustments |
| `leakage_report.py` | Loss by reason, payment method, hour (IST) |
| `counterfactual.py` | Baseline “remind all” vs smart strategy |
| `recovery_budget.py` | ₹50k budget allocator by ROI |
| `ml_recovery.py` | sklearn logistic regression → recovery probability (not LLM) |
| `llm_client.py` | Unified Gemini / OpenAI wrapper (`LLM_PROVIDER=auto`) |
| `llm_diagnosis.py` | LLM fallback for unknown / low-confidence failures |
| `llm_messages.py` | LLM-personalized recovery SMS/email copy |
| `llm_reasoning.py` | Leakage narrative + per-case score explanation |
| `promise_parser.py` | Regex first, then optional LLM for voice promises |
| `downtime.py` | Active outage tracking → DELAYED interventions |

---

## 4. Directory structure

```
razorpay/
├── app/
│   ├── main.py              # FastAPI app, metrics routes, scheduler
│   ├── run.py               # uvicorn entrypoint
│   ├── config.py            # Settings from .env
│   ├── database.py          # SQLite + lightweight migrations
│   ├── webhooks/razorpay.py # Webhook ingest + handlers
│   ├── diagnosis/           # Rule engine (110+ reasons)
│   ├── execution/           # Executor, stopping rules, messages
│   ├── lab/                 # Scenario fire, activity, journey APIs
│   ├── models/              # audit, intervention, promise, escalation
│   ├── services/            # Intelligence, voice, notifications, etc.
│   └── ui/app.html          # Unified dashboard UI
├── data/                    # SQLite DB (gitignored)
├── payments_error_reasons.xlsx
├── .env.example
├── PROJECT_ARCHITECTURE.md  # This file
└── requirements.txt
```

---

## 5. Data model

### `audit_events`

Every detected revenue event (webhook or lab fire): failure, pending, success, subscription state.

Key fields: `event_type`, `error_reason`, `amount_paise`, `payment_method`, `recovery_score`, `status`.

### `interventions`

Recovery actions taken: channel, payment link, message, recovered amount.

Statuses: `sent`, `recovered`, `delayed`, `reused_link`, `sent_no_link`, `watching`.

### `promises_to_pay`

Voice-only promise-to-pay with scheduled reminder (LLM or regex date parsing).

### `escalation_cases`

Human sales handoff queue for high-value cases (≥₹25,000, score ≥55).

### `scheduled_actions`

Background email reminders for promise dates (45s scheduler loop).

---

## 6. Core pipeline detail

### 6.1 Webhook ingest (`POST /webhooks/razorpay`)

Handled events:

| Event | Action |
|-------|--------|
| `payment.failed` | Diagnose → score → execute |
| `payment.pending` | Late auth watch (no customer spam) |
| `payment.authorized` | Optional auto-capture |
| `order.paid`, `payment.captured`, `payment_link.paid` | Attribute recovery (idempotent) |
| `subscription.halted` | Voice + revival playbook |
| `payment_link.expired` | Regenerate link |

**Reconciliation:** duplicate success webhooks are ignored; `GET /webhooks/reconcile` syncs audit rows with recovered interventions.

### 6.2 Diagnosis

Rule-based mapping from Razorpay `error_reason` / `error_source` / `error_step` to actions like:

- `urgent_otp_retry`
- `regenerate_payment_link`
- `halted_revival_job`
- `mandate_retry_sequence`
- `delay_retry` (downtime)

**Known reasons (110+):** rule lookup in `diagnosis/engine.py` — fast, deterministic.  
**Unknown / `safe_default` path:** optional LLM enrich via `llm_diagnosis.py` when `LLM_DIAGNOSIS_ENABLED=true`.

### 6.3 Recovery score (0–100)

Factors: failure reason recoverability, customer persona/history, amount tier, channel cost, stopping rules, **learn loop boost**.

Outputs: `pursue`, `expected_recovery_paise`, `recovery_cost_paise`, `expected_roi`, positive/negative factors.

### 6.4 Execute

1. Downtime check → delay if bank/gateway outage
2. Stopping rules → skip if over nudge cap
3. Create/reuse Razorpay payment link
4. Send email (Resend) / SMS (Twilio) / voice (ElevenLabs → Twilio fallback → simulated IVR)
5. Apply **discount tier** when ROI-positive (max ₹500)
6. Queue **human escalation** for high-value cases
7. Persist score on audit row

### 6.5 Promise-to-pay (voice only)

API `POST /lab/promise` returns **400** for non-voice cases. Rationale: SMS/email are one-way in this demo; only IVR captures inbound intent.

**UI (Case history tab):**

- Record promises only from **Case history** → select a voice case → journey panel textarea (`data-promise-input`).
- Dashboard tab shows a hint only (no duplicate input) — avoids recording the wrong text.
- Fixed v0.8.2: duplicate `id="promise-input"` caused JS to read a hidden dashboard field; now uses `getPromiseInputEl()` + `data-promise-input`.

**Parsing pipeline (`promise_parser.py`):**

1. **Regex/heuristic** — always runs first (Hinglish + English):
   - `Friday tak pay karunga` → `regex_hinglish_weekday`
   - `I will pay on next Friday` → `regex_next_weekday` or `regex_english_weekday`
   - `kal pay kar dunga` → `regex_hinglish_kal`
2. **LLM** (Gemini/OpenAI if key set) — when regex confidence is low or text is messy.
3. Response includes `parsed_by` (e.g. `regex_next_weekday`, `gemini`, `no_llm_key`) for audit.

If Gemini quota is exceeded (429), the system falls back to regex — no crash.

### 6.6 DELAYED status (downtime-aware recovery)

When Activity or the pipeline shows **DELAYED**, the failure was diagnosed correctly but execution was **paused** because a bank/gateway outage is active.

| Piece | Role |
|-------|------|
| `downtime.py` | Tracks simulated or webhook-driven outages per bank/gateway |
| `should_delay_for_downtime()` | Matches failure reason + outage window |
| `executor.py` | Sets intervention status `delayed`, action `delay_retry` — **no SMS/email/voice** |
| UI pipeline | Stage shows **DELAYED** — hint: *outage window; nudge after bank/gateway recovers* |

**Demo:** Fire **Bank downtime** scenario → Activity: `Delayed (bank/gateway downtime)`. This is compliance (don’t spam during HDFC/issuer outages), not ML scoring.

**Not DELAYED:** `insufficient_funds` delayed retry (next morning) is a **scheduled** playbook — different from outage delay.

### 6.7 AI, ML, and rules — where each is used

> **Judge one-liner:** Rules diagnose known failures and enforce compliance; ML scores pursuit ROI; Gemini optionally personalizes messages, parses messy voice promises, narrates leakage, and handles unknown failures — always with rule/regex fallbacks.

| Layer | Technology | Used for | Not used for | Fallback if off |
|-------|------------|----------|--------------|-------------------|
| **Rules** | `diagnosis/engine.py`, stopping rules, downtime | Known `error_reason` → action; max nudges; outage pause; mandate steps | Creative copy | — |
| **Classical ML** | sklearn logistic regression (`ml_recovery.py`) | Recovery probability 0–100 blend (45% ML + 55% heuristic) | Diagnosis, message text | Heuristic-only score |
| **Learn loop** | SQL aggregates + retrain | Win-rate boost by reason+action | — | No boost |
| **LLM** | Gemini (preferred) or OpenAI via `llm_client.py` | Unknown failure enrich; message rewrite; promise NLP; leakage narrative; score explanation | Payment execution, webhook detection | Templates + regex |

**Five LLM touchpoints:**

| Module | Trigger | Output |
|--------|---------|--------|
| `llm_diagnosis.py` | Unknown / low-confidence `error_reason` | Action + channel (`diagnosis_path: llm_diagnosis`) |
| `llm_messages.py` | Before send (`LLM_MESSAGES_ENABLED`) | Personalized SMS/email body |
| `promise_parser.py` | Voice promise text | `promised_date` + `parsed_by` |
| `llm_reasoning.py` | Leakage report (`include_ai=true`) | Narrative insights |
| `llm_reasoning.explain_recovery_decision` | After scoring | One-liner in `recovery_score_json` |

**Purely rule-based (no LLM):** DELAYED, STOPPED, WATCHING, downtime gate, stopping rules, mandate sequencer, Hinglish IVR script template (`voice.py` — templated, not generated).

**How to see it in the UI:** Activity `diagnosis_path`; promise API `parsed_by`; toast shows submitted `raw_text`; `/health` shows `llm_configured` + `llm_provider`.

---

## 7. API reference (key endpoints)

### UI & health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Unified dashboard UI |
| GET | `/health` | Config status |
| GET | `/docs` | OpenAPI |

### Metrics & intelligence

| Method | Path | Description |
|--------|------|-------------|
| GET | `/metrics/summary` | At risk, recovered, rate |
| GET | `/metrics/intelligence` | ERR + recovery plan |
| GET | `/metrics/leak-funnel` | Horizontal funnel |
| GET | `/metrics/leakage` | Method/time/reason leakage report |
| GET | `/metrics/leak-tree` | Hierarchical leak graph (API only — no dashboard panel) |
| GET | `/metrics/learn-loop` | Historical win-rate insights (API only — no dashboard panel) |
| GET | `/metrics/counterfactual` | Baseline vs smart simulator |
| GET | `/metrics/recovery-budget` | ₹50k budget allocation |
| GET | `/metrics/reconcile` | Webhook reconciliation status |

### Lab

| Method | Path | Description |
|--------|------|-------------|
| POST | `/lab/seed-training-batch?count=2000` | **Primary ML training** — 2000 events + recoveries |
| POST | `/lab/seed-batch?count=200` | Smaller demo batch |
| POST | `/lab/seed-batch?training=true&count=2000` | Alias for training batch |
| POST | `/lab/fire/{scenario_id}` | Fire single scenario |
| GET | `/lab/activity` | Activity feed |
| GET | `/lab/journey/{audit_id}` | Full case journey |
| POST | `/lab/promise` | Voice promise-to-pay |
| GET | `/lab/escalations` | Human escalation queue |
| GET | `/lab/leakage-report` | Same as `/metrics/leakage` |

---

## 7.1 Dashboard UI (unified `/` — v0.8.3)

| Section | Content |
|---------|---------|
| Hero KPIs | Total at risk, revenue recovered, recovery rate, cases chasing |
| Recovery performance | Bar chart — per-case ₹ (green = recovered) |
| Portfolio breakdown | Donut — pursuing / stopped / delayed / recovered |
| Stats strip | Open at risk, stopped by rules, still to recover |
| Leak funnel | Horizontal stack by outcome |
| Playbook mix | Chips: retry, remind, voice, STOP, delay, watch, recovered |
| Leakage insights | Method + hour tables; AI narrative on manual refresh |
| Counterfactual + budget | Naive vs smart comparison; ₹50k allocator |
| Escalation queue | ≥₹25k B2B cases |
| Recovery by category | Batch measured recovery table |

**Not in UI (backend only):** Learn loop panel, leak graph tree panel (removed v0.8.3 to reduce clutter; APIs remain).

**Run note:** If port 8000 is occupied, `python -m app.run` falls back to 8001 and prints the correct URL. UI shows a red banner when `/health` is not RevRecover (wrong app on that port).

---

## 8. Feature matrix (vision vs built)

| Feature | Status | Notes |
|---------|--------|-------|
| **ML recovery score** | ✅ | sklearn logistic regression, blends 45% ML + 55% heuristic |
| **Learn loop** | ✅ backend | SQL aggregates + retrains ML — **no dashboard panel** (v0.8.3) |
| Webhook → diagnose → execute | ✅ | Core pipeline |
| Recovery score + ERR + ROI | ✅ | Hero KPIs + charts (Chart.js bar + donut) |
| STOP / stopping rules | ✅ | Compliance + low score |
| Leakage report (method/time) | ✅ | Dashboard panel + optional Gemini narrative |
| Leak graph tree | ✅ API | `/metrics/leak-tree` — **removed from dashboard UI** (v0.8.3) |
| Counterfactual simulator | ✅ | Baseline vs smart — dashboard panel |
| Recovery budget ₹50k | ✅ | ROI-ranked allocator |
| Batch seed 2000 + ML training | ✅ | `POST /lab/seed-training-batch` |
| LLM layer (Gemini/OpenAI) | ⚠️ | Unknown diagnosis, messages, promises, leakage narrative, explanations — regex/templates if no key |
| Promise UI + parser fix | ✅ | v0.8.2 — `data-promise-input`, English/Hinglish regex, LLM fallback |
| ElevenLabs + Twilio voice | ⚠️ | Wired; needs API keys + Twilio-linked number |
| Discount / incentive tier | ✅ | ROI-gated, max ₹500 |
| Human escalation queue | ✅ | Model + UI + API |
| Webhook reconciliation | ✅ | Idempotent attribution + reconcile endpoint |
| Promise-to-pay | ✅ | Voice-only |
| Mandate sequencer | ✅ | 3-step SMS→email |
| Downtime delay | ✅ | Bank/gateway outage |
| Late auth watch | ✅ | No customer spam |

---

## 9. API keys & environment variables

### Required

| Variable | Where to get it |
|----------|-----------------|
| `RAZORPAY_KEY_ID` | [Razorpay Dashboard](https://dashboard.razorpay.com) → API Keys (Test mode) |
| `RAZORPAY_KEY_SECRET` | Same as above |
| `RAZORPAY_WEBHOOK_SECRET` | Dashboard → Webhooks → create endpoint → Secret |

Webhook URL for local dev: use ngrok or poll via `POST /lab/sync-razorpay` after paying a link.

### Recommended (live notifications)

| Variable | Service | Purpose |
|----------|---------|---------|
| `RESEND_API_KEY` | [resend.com](https://resend.com) | Recovery emails |
| `RESEND_FROM_EMAIL` | Resend | Sender address |

### Optional — SMS

| Variable | Service |
|----------|---------|
| `TWILIO_ACCOUNT_SID` | [twilio.com](https://twilio.com) |
| `TWILIO_AUTH_TOKEN` | Twilio |
| `TWILIO_FROM_NUMBER` | Twilio phone number |

### Optional — AI voice (ElevenLabs)

| Variable | Service |
|----------|---------|
| `ELEVENLABS_API_KEY` | [elevenlabs.io](https://elevenlabs.io) |
| `ELEVENLABS_AGENT_ID` | ElevenLabs Conversational AI agent |
| `ELEVENLABS_AGENT_PHONE_NUMBER_ID` | Twilio-linked number in ElevenLabs |

Without ElevenLabs/Twilio, voice runs in **simulated Hinglish IVR** mode (logged + shown in UI).

### Optional — LLM (Gemini recommended)

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` | From [Google AI Studio](https://aistudio.google.com/api-keys) |
| `GEMINI_MODEL` | Default `gemini-2.0-flash` |
| `LLM_PROVIDER` | `auto` (Gemini if key set), `gemini`, or `openai` |
| `OPENAI_API_KEY` | Optional fallback if no Gemini key |

Without any LLM key: promise parsing uses regex and leakage uses rule-based insights.

### Optional — OpenAI only (legacy)

### Other

| Variable | Default | Purpose |
|----------|---------|---------|
| `RECOVERY_BUDGET_RUPEES` | 50000 | Budget allocator cap |
| `ML_SCORING_ENABLED` | true | Offline sklearn recovery probability |
| `ML_BLEND_WEIGHT` | 0.45 | How much ML vs heuristic in final score |
| `LLM_DIAGNOSIS_ENABLED` | true | LLM for unknown failure reasons |
| `LLM_MESSAGES_ENABLED` | true | LLM-personalized recovery copy |
| `LLM_EXPLANATIONS_ENABLED` | true | LLM one-liner on case journey |
| `DEMO_CUSTOMER_EMAIL` | — | Lab fires default email |
| `AUTO_CAPTURE_ENABLED` | true | Capture on `payment.authorized` |

---

## 10. Demo personas (`app/data/demo_customers.json`)

| Email | Persona | Expected score |
|-------|---------|----------------|
| `ganeshsuraj29@gmail.com` | Loyal repeat buyer | High |
| `loyal@demo.revrecover.test` | Loyal | High |
| `b2b@demo.revrecover.test` | B2B | Medium-high |
| `churned@demo.revrecover.test` | Churned | Low / STOP |
| `newuser@demo.revrecover.test` | New user | Low |

---

## 11. Why some features were not in v1

| Gap | Reason | Now |
|-----|--------|-----|
| Learn loop | Needed historical recovery data | Built with in-session heuristic learning |
| Leakage time/method | Audit rows lacked `payment_method` + hour bias | Seed + webhook capture method |
| Sankey tree | Complex viz library | Nested tree (same data, simpler) |
| Counterfactual / budget | Intelligence layer priority | Built |
| ElevenLabs | Needs paid APIs + Twilio number setup | Code ready; keys optional |
| LLM in diagnosis | Hackathon reliability + cost | Optional `llm_diagnosis` for unknown reasons only |

---

## 12. ML training data strategy (chosen approach)

We evaluated four options for training the recovery probability model. **We chose #2** for best effort-to-credibility ratio at the hackathon.

| # | Approach | Verdict |
|---|----------|---------|
| 1 | DB + synthetic Razorpay-catalog priors only | Good fallback, weak sample size |
| **2** | **Seed 2000 + reason-weighted simulated recoveries** | **✅ Selected — primary pipeline** |
| 3 | Import Kaggle + manual column mapping | Medium effort, weak Razorpay field alignment |
| 4 | Razorpay API bulk export | Strong story, needs many real test payments first |

### Why seed 2000 + simulated recoveries?

- Razorpay publishes **no public recovery dataset**
- Kaggle datasets lack `error_reason` / `error_source` / `error_step`
- Our seed pipeline uses the **same Razorpay error-reason taxonomy** as `payments_error_reasons.xlsx`
- Recovery labels are **reason-weighted** (e.g. OTP 78%, cancelled 22%) — not random coin flips
- After seeding, the ML model trains on **100% database rows** (no synthetic padding when ≥100 interventions)

### How to run (one click)

**UI:** Dashboard → **Seed 2000 ML batch**

**API:**
```http
POST /lab/seed-training-batch?count=2000
```

**CLI:**
```bash
curl -X POST "http://localhost:8000/lab/seed-training-batch?count=2000"
```

### What gets created

| Output | Typical count |
|--------|----------------|
| Audit events | 2000 |
| Interventions | ~1700 (72% intervention_sent) |
| Simulated recoveries | ~550–650 (reason-weighted) |
| ML training rows | All interventions (real DB) |
| `training_source` | `database_only` |

### Label logic (P(recovered) by failure reason)

| Reason | Prior | Razorpay playbook |
|--------|-------|-------------------|
| `incorrect_otp` | 78% | Urgent OTP retry |
| `otp_expired` | 72% | Immediate retry |
| `insufficient_funds` | 55% | Delayed retry |
| `payment_cancelled` | 22% | Soft nudge once |
| `bank_technical_error` | 48% | Delay during outage |
| `invalid_vpa` | 12% | STOP / alternate method |
| … | (14 reasons) | See `REASON_RECOVERY_PRIORS` in `ml_recovery.py` |

Each label adds ±8% noise so the model learns patterns, not memorization.

### Model retrain trigger

After every training batch:

1. `refresh_learned_rates()` — SQL win-rate insights
2. `train_recovery_model()` — sklearn logistic regression on joined `interventions` + `audit_events`
3. Model saved to `data/recovery_model.joblib`

Check status:
```http
GET /metrics/ml-status
```

Example response:
```json
{
  "enabled": true,
  "model_loaded": true,
  "samples_total": 1680,
  "samples_real": 1680,
  "positive_rate": 38.2,
  "training_source": "database_only"
}
```

### Judge talking point

> “We don’t use random Kaggle data. We train on **2000 merchant failure scenarios** aligned to Razorpay’s error catalog, with **recovery outcomes weighted by failure type**. As real webhooks accumulate, the model retrains on **only real outcomes** — the seed batch bootstraps us for demo day.”

### After hackathon (production path)

Replace seed labels with **real webhook outcomes**:

```
payment.failed → intervention → order.paid / payment_link.paid = label 1
```

No code change needed — `train_recovery_model()` already reads from SQLite.

---

## 13. Operations

### Reset demo data

```http
POST /lab/reset?confirm=true
```

### Sync paid links (no webhook)

```http
POST /lab/sync-razorpay
```

### Run tests / smoke

```bash
python -m app.run
# In another terminal:
curl http://localhost:8000/health
curl -X POST "http://localhost:8000/lab/seed-training-batch?count=2000"
curl http://localhost:8000/metrics/ml-status
```

---

## 14. Security notes

- Never commit `.env` (gitignored)
- Webhook signature verification when `RAZORPAY_WEBHOOK_SECRET` is set
- Test mode keys only for hackathon demo
- Recovery actions never execute payments without Razorpay customer consent flows

---

## 15. Version history

| Version | Highlights |
|---------|------------|
| 0.8.3 | Dashboard charts (Chart.js), hero KPIs, port 8001 fallback, backend health banner, docs sync |
| 0.8.2 | Promise input UI fix (`data-promise-input`), English/Hinglish regex parser, AI/ML docs |
| 0.8.1 | Seed 2000 ML training pipeline, reason-weighted recoveries, database-only training |
| 0.8.0 | Learn loop, leakage report, counterfactual, budget, escalation, reconciliation, ElevenLabs wiring |
| 0.7.0 | ERR intelligence, recovery score, batch seed, journey UI |
| 0.5.0 | Core webhook pipeline, stopping rules, lab scenarios |

---

*Built for Razorpay Buildathon 2026 — Track 03: AI Revenue Recovery*
