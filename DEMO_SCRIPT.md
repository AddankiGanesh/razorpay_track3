# RevRecover — 2-minute judge demo script

## Before you start

```powershell
cd C:\Users\ganes\OneDrive\Desktop\razorpay
.\.venv\Scripts\Activate.ps1
python -m app.run
```

Optional (real Razorpay webhooks): `ngrok http 8000` + webhook URL set.

Open **http://localhost:8000/** (or the URL printed by `python -m app.run` if port 8000 is busy).

---

## Script

### 1. Reset (5 sec)
Click **Reset demo data** → metrics go to ₹0.

### 2. Same failure family, different actions (30 sec)
| Fire | Show judges |
|------|-------------|
| **Wrong OTP** | Action `retry_with_new_otp` — urgent |
| **Cancelled** or **Checkout abandoned** | Action `soft_nudge_once` — gentle, once |

**Pitch line:** “Razorpay tells us *why* it failed. We choose *different* recovery playbooks — not one generic SMS.”

### 3. Recover money (30 sec)
- Open **Pay / recover** (Razorpay link or Demo pay if rate-limited)
- Demo pay → **Simulate successful recovery**
- Metrics: **Recovered** rises; Activity shows **Recovered**

**Pitch line:** “Measured money recovered with attribution to the intervention — the track bar.”

### 4. Compliance (20 sec)
- **Bank downtime** → Activity: **Delayed (bank/gateway downtime)** — outage pause, not spam
- **Case history** tab → select a **voice** case (e.g. Halted subscription) → journey panel
- Type promise: `I will pay next Friday` or `Friday tak pay karunga` → **Record promise** (check toast shows your exact text)
- Fire Wrong OTP again → **Stopped** (`promise_to_pay_until_...`)

**Pitch line:** “Bounded recovery — DELAYED during outages, promise-to-pay suppression, not spam.”

### 5. Differentiator (25 sec)
- **Mandate debit declined** → Activity shows **mandate_retry_sequence** step 1/3 (SMS → email → re-register, then stop)
- **Halted subscription** → channel may show **voice**; message includes Hinglish IVR script
- **Late auth** → **Watching (late auth — no nudge)**
- **B2B expired** → regenerate + high-value voice path
- Point at **Batch recovery by category** panel on Overview

**Pitch line:** “Bounded mandate sequencer + Hinglish voice + late-auth watch — measured ₹ across the batch.”

### 6. Close (10 sec)
Point at dashboard hero KPIs: At risk · Recovered · Rate · Cases chasing.
Scroll to **Recovery by category** and **Portfolio breakdown** chart.

**Optional AI line:** “Known failures = rules. Score = ML (backend). Copy and messy promises = Gemini — with regex fallback if quota runs out.”

---

## One-liner

> Razorpay is the thermometer. RevRecover is the doctor — diagnose, decide with stopping rules, execute, and prove ₹ recovered.
