# RevRecover — AI Revenue Recovery Operator

**Razorpay AI Buildathon · Track 03**

RevRecover is an AI-powered revenue recovery layer that sits **on top of Razorpay**. When a payment fails, Razorpay tells you *that* money is at risk — RevRecover decides **why it failed**, **whether it's worth chasing**, **what to do** (chase / stop / delay / watch), **how to execute**, and **proves which intervention recovered the money**.

[![Track 03](https://img.shields.io/badge/Razorpay-Track%2003-0C4A6E)](https://github.com/AddankiGanesh/razorpay_track3)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)

---

## Table of contents

1. [The problem](#the-problem)
2. [Why RevRecover exists](#why-revrecover-exists)
3. [What we built](#what-we-built)
4. [Architecture](#architecture)
5. [Tech stack](#tech-stack)
6. [Prerequisites & API keys](#prerequisites--api-keys)
7. [Installation & run](#installation--run)
8. [Judge demo flow](#judge-demo-flow)
9. [Project structure](#project-structure)
10. [API overview](#api-overview)
11. [Documentation](#documentation)
12. [Team / license](#team--license)

---

## The problem

Imagine a flash sale ends at 11 PM. The merchant expected **₹3 lakh** — but the dashboard shows **FAILED**.

Three customers failed the same night:

| Customer | What happened | Wrong response |
|----------|---------------|----------------|
| **Wrong OTP** | Typed wrong OTP — still wants to pay | Generic SMS too late → lost sale |
| **Cancelled checkout** | Pressed back — changed mind | 5 reminders → harassment |
| **Bank outage** | Bank was down — can't pay | Immediate retry → wasted spend + annoyance |

**Same word: FAILED. Three completely different stories.**

Most merchants either:
- Blast the same “please retry” to everyone, or
- Manually read error codes and guess the next step.

Both leak revenue and damage customer trust.

---

## Why RevRecover exists

**Razorpay already provides:**
- Webhooks (`payment.failed`, `subscription.halted`, …)
- Payment Links + customer notify
- Subscription retry schedules
- Sandbox, APIs, test mode

**What merchants still do manually:**
1. Interpret `error_reason` — OTP vs cancelled vs bank down
2. Choose channel & timing — SMS, email, voice, or wait
3. Apply **stopping rules** — when *not* to nudge
4. **Prove ₹ recovered** after an intervention

RevRecover is the **decision + recovery layer** that answers those four questions automatically — with scoring, ROI gates, compliance caps, and full audit attribution.

> **Razorpay is the thermometer. RevRecover is the doctor.**

---

## What we built

### Core pipeline (every case)

```
DETECT → DIAGNOSE → DECIDE → EXECUTE → PROVE
```

| Step | What happens |
|------|----------------|
| **Detect** | Ingest Razorpay webhooks or fire lab scenarios |
| **Diagnose** | Map **110+** Razorpay error reasons → playbook action |
| **Decide** | Recovery score (0–100), ERR, ROI, stopping rules → **Chase / Stop / Delay / Watch** |
| **Execute** | Payment link, SMS, email, Hinglish voice IVR, human escalation |
| **Prove** | On `order.paid` / `payment_link.paid` — attribute ₹ to the intervention |

### Key capabilities

| Feature | Description |
|---------|-------------|
| **Smart routing** | Wrong OTP → urgent retry; cancelled → soft nudge once; bank down → **DELAYED** |
| **Stopping rules** | Max nudges, soft-nudge-once, promise-to-pay suppression |
| **Outage-aware delay** | No SMS/email during bank/gateway outage window |
| **Mandate sequencer** | SMS → email → re-register → STOP |
| **Late auth watch** | Poll pending payments — no customer spam |
| **Halted subscription revival** | Voice + Hinglish IVR + promise-to-pay |
| **B2B / high-value** | Regenerate link + **human escalation queue** (≥ ₹25k) |
| **ML scoring** | sklearn logistic regression blends with rules |
| **LLM layer** | Groq / Gemini / Grok / OpenAI for copy, promises, unknown failures |
| **Measured recovery** | Dashboard KPIs, recovery by category, counterfactual vs naive “remind all” |
| **Controlled autonomy** | AI suggests; **policy layer** controls money movement |

### Unified dashboard (`/`)

- Hero KPIs: at risk, recovered, recovery rate, cases chasing
- Charts: recovery per case + portfolio breakdown
- Leak funnel, leakage insights, smart vs naive counterfactual
- Recovery budget allocator (₹50k cap)
- Human escalation queue
- **14 lab scenarios** aligned to Razorpay error taxonomy
- Case history with journey timeline + demo pay fallback

---

## Architecture

```
                    ┌─────────────────────────────────────┐
                    │   Razorpay webhooks / Lab scenarios │
                    └──────────────────┬──────────────────┘
                                       ▼
                    ┌─────────────────────────────────────┐
                    │  Detect + Audit (audit_events)      │
                    └──────────────────┬──────────────────┘
                                       ▼
                    ┌─────────────────────────────────────┐
                    │  Diagnosis Engine (110+ reasons)    │
                    └──────────────────┬──────────────────┘
                                       ▼
                    ┌─────────────────────────────────────┐
                    │  Customer Context + Recovery Score  │
                    │  (rules + ML + ERR + ROI)           │
                    └──────────────────┬──────────────────┘
                                       ▼
                    ┌─────────────────────────────────────┐
                    │  Stopping Rules (compliance caps)   │
                    └──────────────────┬──────────────────┘
                                       ▼
                    ┌─────────────────────────────────────┐
                    │  Execute Recovery                   │
                    │  link · SMS · email · voice · human │
                    └──────────────────┬──────────────────┘
                                       ▼
                    ┌─────────────────────────────────────┐
                    │  Attribute Success (idempotent)     │
                    │  order.paid / payment_link.paid     │
                    └─────────────────────────────────────┘
```

**Intelligence modules:** `recovery_economics`, `recovery_score`, `ml_recovery`, `llm_client`, `counterfactual`, `recovery_budget`, `leakage_report`, `downtime`, `promise_parser`, `payment_link_sync`.

Full detail: **[PROJECT_ARCHITECTURE.md](./PROJECT_ARCHITECTURE.md)**

---

## Tech stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11+, FastAPI, Uvicorn |
| Database | SQLAlchemy + SQLite (`data/revrecover.db`) |
| Payments | Razorpay Python SDK (test mode) |
| ML | scikit-learn (offline recovery probability) |
| LLM | Groq / Gemini / Grok / OpenAI (optional) |
| Email | Resend (optional) |
| SMS / Voice | Twilio + ElevenLabs (optional stubs if unset) |
| UI | Single-page dashboard (`app/ui/app.html`) + Chart.js |

---

## Prerequisites & API keys

### Required (minimum to run)

| Variable | Where to get it | Purpose |
|----------|-----------------|---------|
| `RAZORPAY_KEY_ID` | [Razorpay Dashboard](https://dashboard.razorpay.com/) → Settings → API Keys (Test) | Create orders & payment links |
| `RAZORPAY_KEY_SECRET` | Same | API authentication |
| `RAZORPAY_WEBHOOK_SECRET` | Dashboard → Webhooks → your webhook | Verify webhook signatures |

Copy `.env.example` → `.env` and fill at least the three Razorpay values above.

### Recommended for demo

| Variable | Purpose |
|----------|---------|
| `DEMO_CUSTOMER_EMAIL` | Email used when firing lab scenarios |
| `DEMO_CUSTOMER_CONTACT` | Phone for SMS/voice demos |

### Optional — LLM (pick one provider)

| Provider | Variables | Get key |
|----------|-----------|---------|
| **Groq** (default in example) | `GROQ_API_KEY`, `LLM_PROVIDER=groq` | [console.groq.com](https://console.groq.com) |
| **Gemini** | `GEMINI_API_KEY`, `LLM_PROVIDER=auto` | [aistudio.google.com](https://aistudio.google.com/api-keys) |
| **Grok (xAI)** | `GROK_API_KEY`, `LLM_PROVIDER=grok` | [console.x.ai](https://console.x.ai/) |
| **OpenAI** | `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com/) |

**Without any LLM key:** regex promise parsing, template messages, and rule-based diagnosis still work.

### Optional — notifications

| Service | Variables | If empty |
|---------|-----------|----------|
| Resend email | `RESEND_API_KEY`, `RESEND_FROM_EMAIL` | Logged stub |
| Twilio SMS | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | Logged stub |
| ElevenLabs voice | `ELEVENLABS_API_KEY`, agent IDs | Hinglish script logged |

### Optional — ML

| Variable | Default | Purpose |
|----------|---------|---------|
| `ML_SCORING_ENABLED` | `true` | Blend sklearn score into recovery ranking |
| `ML_BLEND_WEIGHT` | `0.45` | Weight of ML vs rules |

See **[.env.example](./.env.example)** for the full list.

> **Never commit `.env`** — it is gitignored. Only commit `.env.example`.

---

## Installation & run

### 1. Clone

```bash
git clone https://github.com/AddankiGanesh/razorpay_track3.git
cd razorpay_track3
```

### 2. Virtual environment

```powershell
# Windows
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
# Edit .env — add Razorpay test keys (required)
```

### 5. Start the server

```bash
python -m app.run
```

Open the URL printed in the terminal:
- Usually **http://127.0.0.1:8000/**
- If port 8000 is busy, RevRecover auto-falls back to **http://127.0.0.1:8001/**

### 6. Real Razorpay webhooks (optional)

For live payment-link callbacks (not required for lab demo):

```bash
ngrok http 8000   # or 8001
```

Set webhook URL in Razorpay Dashboard:

```
https://YOUR-NGROK-URL/webhooks/razorpay
```

### Test payment card (Razorpay test mode)

| Field | Value |
|-------|-------|
| Card | `5267 3181 8797 5449` |
| OTP | `1234` |
| UPI | `success@razorpay` |

### Razorpay test-mode payment link cap

Test mode allows **~30 payment links total**. If link creation fails:
- RevRecover **reuses** existing unpaid links when possible
- Use **Demo pay** at `/pay/{intervention_id}` → **Simulate successful recovery**

---

## Judge demo flow

See **[DEMO_SCRIPT.md](./DEMO_SCRIPT.md)** and **[FINAL_PITCH_SCRIPT.md](./FINAL_PITCH_SCRIPT.md)**.

**Quick 2-minute flow:**

1. **Reset demo data** on the UI  
2. Fire **Wrong OTP** → CHASE → Demo pay → Recovered ₹ rises  
3. Fire **Customer cancelled** → soft nudge / STOP  
4. Fire **Bank downtime** → **DELAYED**  
5. Open **Case history** → voice case → record promise (`Friday tak pay karunga`)  
6. Show **Dashboard** — at risk, recovered, recovery by category  

**Pitch deck:** `RevRecover_Beautiful_Pitch_Deck.pptx`  
**Pitch script PDF:** `FINAL_PITCH_SCRIPT.pdf`

---

## Project structure

```
razorpay_track3/
├── app/
│   ├── main.py              # FastAPI app + metrics routes
│   ├── run.py               # uvicorn entry (port fallback)
│   ├── config.py            # Settings from .env
│   ├── database.py          # SQLite
│   ├── webhooks/            # Razorpay webhook handlers
│   ├── diagnosis/           # Rule engine (110+ reasons)
│   ├── execution/           # Recovery executor + stopping rules
│   ├── lab/                 # Scenario fire, activity, journey
│   ├── services/            # ML, LLM, metrics, voice, etc.
│   └── ui/app.html          # Unified dashboard
├── scripts/                 # Batch scenarios, pitch deck generator
├── data/                    # SQLite DB (created at runtime, gitignored)
├── payments_error_reasons.xlsx
├── requirements.txt
├── .env.example
├── PROJECT_ARCHITECTURE.md  # Deep technical reference
├── DEMO_SCRIPT.md
└── FINAL_PITCH_SCRIPT.md
```

---

## API overview

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Unified dashboard UI |
| GET | `/health` | Service + integration status |
| GET | `/docs` | Swagger API docs |
| POST | `/webhooks/razorpay` | Razorpay webhook ingest |
| GET | `/lab/scenarios` | List 14 demo scenarios |
| POST | `/lab/fire/{scenario_id}` | Fire one scenario |
| POST | `/lab/fire-all` | Fire all scenarios |
| POST | `/lab/reset?confirm=true` | Reset demo data |
| GET | `/lab/activity` | Case history feed |
| GET | `/lab/journey/{audit_id}` | Case journey timeline |
| POST | `/lab/promise` | Record promise-to-pay |
| GET | `/metrics/summary` | Hero KPIs |
| GET | `/metrics/batch` | Recovery by category |
| GET | `/metrics/counterfactual` | Smart vs naive comparison |
| POST | `/pay/{id}/simulate` | Demo recovery (no Razorpay link needed) |

Full API catalog: **GET `/api`** when server is running.

---

## Documentation

| File | Contents |
|------|----------|
| [PROJECT_ARCHITECTURE.md](./PROJECT_ARCHITECTURE.md) | Full architecture, services, ML, env vars |
| [PROJECT_CONTEXT.md](./PROJECT_CONTEXT.md) | Track rubric, failure catalog, pitch narrative |
| [DEMO_SCRIPT.md](./DEMO_SCRIPT.md) | 2-minute judge walkthrough |
| [FINAL_PITCH_SCRIPT.md](./FINAL_PITCH_SCRIPT.md) | 5-minute pitch script (aligned to deck) |
| [.env.example](./.env.example) | All environment variables |

---

## Team / license

Built for **Razorpay AI Buildathon — Track 03: AI Revenue Recovery**.

**Repository:** [github.com/AddankiGanesh/razorpay_track3](https://github.com/AddankiGanesh/razorpay_track3)

---

## RevRecover vs Razorpay alone

| Capability | Razorpay | RevRecover |
|------------|----------|------------|
| Payment events & links | ✅ | Uses after diagnosis |
| 110+ reason-specific playbooks | ❌ | ✅ |
| Chase / Stop / Delay / Watch | ❌ | ✅ |
| Stopping rules & compliance caps | Partial | ✅ |
| Outage-aware delay | ❌ | ✅ |
| Promise-to-pay suppression | ❌ | ✅ |
| Hinglish voice IVR path | ❌ | ✅ |
| Human escalation (≥ ₹25k) | ❌ | ✅ |
| Measured ₹ attribution | Partial | ✅ full audit trail |
| ML + LLM recovery intelligence | ❌ | ✅ optional layers |

**Don't chase every failed payment. Chase every payment worth saving.**
