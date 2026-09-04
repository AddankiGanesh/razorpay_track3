# RevRecover — 5-Minute Pitch Script (final)

**Goal:** First 2 minutes → judges think *"This isn't another payment-failure notification bot — show me."*  
**Remaining 3 minutes** → live proof on the website.

**Length:** ~5:00  
**Website:** URL from terminal after `python -m app.run` (often `http://127.0.0.1:8001/`)  
**Slides:** `RevRecover_Pitch_Deck.pptx` (16 slides)  
**Before record:** Reset → confirm email → test **Fire Wrong OTP** once.

---

## Golden rules (read before recording)

1. **Minutes 0–2:** Story + tension. **No** FastAPI, SQLAlchemy, Gemini, Groq, sklearn, or API lists.
2. **Slides show:** `FAILED → WHY? → DECISION → ₹ RECOVERED` — **your voice tells the story.**
3. **Pause** after emotional lines (1–2 seconds). Silence sells.
4. **Don't start with** "Good morning judges, we are team…"
5. At **1:55** stop explaining. Say the hook line. **Start the demo.**

---

## How to read the tables

| Column | Meaning |
|--------|---------|
| **SHOW** | Slide number OR website tab |
| **CLICK / DO** | Mouse / screen actions |
| **SAY** | Exact lines (natural pace, not rushed) |

---

# ACT 1 — HOOK THE JUDGES (0:00–2:00) · Slides only

### 0:00–0:15 · The situation

| | |
|--|--|
| **SHOW** | **Slide 2** — "11 PM. Flash sale. Money at risk." *(or black screen + your face)* |
| **CLICK / DO** | Face to camera OR full-screen slide. **No team intro yet.** |
| **SAY** | "Imagine it's **11 PM**." |
| **SAY** | "Your biggest flash sale of the month just ended." |
| **SAY** | "You expected **₹3 lakh** in payments." |
| **SAY** | "And your dashboard says… **FAILED**." |
| **PAUSE** | 1–2 seconds. Let it land. |
| **SAY** | "But here's the problem. **Failed** doesn't tell you what to do next." |

---

### 0:15–0:50 · Three customers

| | |
|--|--|
| **SHOW** | **Slide 3** — "Three customers — same night" |
| **CLICK / DO** | Stay on slide. Point to each name as you speak. |
| **SAY** | "Let me introduce you to **three customers** from that same night." |
| **SAY** | "**Rahul** entered his card, reached OTP… and entered the **wrong OTP**. He **wants** to pay. This is a **high-intent** customer." |
| **SAY** | "**Priya** reached checkout… and pressed **back**. She changed her mind. Sending her five reminders isn't recovery. **It's harassment.**" |
| **SAY** | "And the third customer? Nothing was wrong with the customer. **The bank was down.** No amount of retrying will make a bank outage disappear." |
| **PAUSE** | Half a beat. |
| **SAY** | "Three payments. Three failures. **Three completely different actions.**" |

---

### 0:50–1:20 · The merchant gap

| | |
|--|--|
| **SHOW** | **Slide 4** — "Razorpay today vs the merchant gap" |
| **CLICK / DO** | Point left (Razorpay), then right (gap). |
| **SAY** | "And that's the gap we're solving." |
| **SAY** | "Razorpay already gives merchants the payment event. It tells them: `payment.failed`, subscription halted, error reasons, payment links and APIs." |
| **SAY** | "But after the payment fails, someone still has to answer **four questions**:" |
| **SAY** | "**Why** did it fail? **Is it worth** recovering? **What** should I do? And **when should I stop?**" |
| **PAUSE** | |
| **SAY** | "That's where **RevRecover** comes in." |

---

### 1:20–1:55 · The WOW moment (architecture, not tech stack)

| | |
|--|--|
| **SHOW** | **Slide 6 or 7** — Pipeline / "What we built" |
| **CLICK / DO** | Walk the pipeline visually — don't read bullet soup. |
| **SAY** | "RevRecover is an **AI Revenue Recovery Operator**." |
| **SAY** | "It takes the payment event… **diagnoses** the failure using **110+ Razorpay error reasons**… **scores** the probability and economics of recovery… **decides** whether to **Chase, Stop, Delay, or Watch**… **executes** through the right channel… and finally **proves** which intervention actually recovered the money." |
| **SAY** *(slowly)* | "**We don't optimize for the number of reminders sent. We optimize for the amount of money recovered.**" |

---

### 1:55–2:00 · Hook into the demo

| | |
|--|--|
| **SHOW** | **Slide 6** → switch to **browser** |
| **CLICK / DO** | Open RevRecover URL → sidebar **◉ Dashboard** (quick glance) → get ready for **⚡ Scenarios** |
| **SAY** | Look at judges. |
| **SAY** | "**So instead of showing you another dashboard… let me show you what RevRecover does when the money actually starts slipping away.**" |

---

# ACT 2 — LIVE PROOF (2:00–4:30) · Website + slide flashes

### 2:00–3:00 · DEMO 1 — Rahul (Wrong OTP)

| | |
|--|--|
| **SHOW** | **Website: ⚡ Scenarios** |
| **CLICK / DO** | 1. **⚡ Scenarios** 2. Email: `ganeshsuraj29@gmail.com` 3. **Wrong OTP** → **Fire** 4. Wait for toast (10–20 sec) 5. **◎ Case history** → click Wrong OTP row |
| **SAY** | "Let's go back to **Rahul**." |
| **SAY** | "Razorpay tells us: **`incorrect_otp**." |
| **SAY** | "RevRecover understands this as a **customer-side authentication failure**." |
| **SAY** | Point at journey / status. "Recovery economics are **positive**. The agent chooses **CHASE**." |
| **SAY** | "Fresh payment link. SMS. **High-priority** recovery." |
| **SAY** | "And notice — we don't just send a message and call it success. When payment succeeds, we **attribute that rupee** back to the intervention that caused it." |

**Optional (strongly recommended for ₹ on screen):**

| **CLICK / DO** | Journey panel → **Demo pay** → **Simulate successful recovery** → **◉ Dashboard** |
| **SAY** | "₹499 **recovered** — measured, attributed, auditable." |

| | |
|--|--|
| **SHOW** | **Slide 8** — flash 3 sec |
| **SAY** | "**Razorpay is the thermometer. RevRecover is the doctor.**" |

---

### 3:00–3:30 · DEMO 2 — Priya (Customer cancelled)

| | |
|--|--|
| **SHOW** | **Website: ⚡ Scenarios** |
| **CLICK / DO** | Fire **Customer cancelled** → **◎ Case history** → click row |
| **SAY** | "Now the **exact opposite** situation." |
| **SAY** | "Priya didn't have a technical problem. She simply **left checkout**." |
| **SAY** | "The economics change. RevRecover doesn't **chase**. It sends **one soft nudge**." |
| **SAY** | "And if she's already been nudged… **STOP**." |
| **PAUSE** | |
| **SAY** | "Because revenue recovery shouldn't mean annoying everyone until someone pays." |
| **SAY** | "**Recover intent. Don't manufacture pressure.**" |

| | |
|--|--|
| **SHOW** | **Slide 9** — brief flash |

---

### 3:30–4:00 · DEMO 3 — Bank outage (slow down here)

| | |
|--|--|
| **SHOW** | **Website: ⚡ Scenarios** |
| **CLICK / DO** | Fire **Bank downtime** → **◎ Case history** → point at **DELAYED** badge |
| **SAY** | "Now something more interesting." |
| **SAY** | "The payment failed because the **bank is experiencing an outage**." |
| **SAY** | "Show status: **DELAYED**." |
| **SAY** | "A naive system sees **failed** and immediately sends another reminder." |
| **SAY** | "RevRecover sees: the customer **can't fix a bank outage**. Why spend recovery money — and why annoy the customer?" |
| **SAY** | "We **pause**. We resume when infrastructure recovers." |
| **PAUSE** | |
| **SAY** *(judge line)* | "**Sometimes the smartest recovery action… is doing nothing.**" |

| | |
|--|--|
| **SHOW** | **Slide 10** — brief flash |

---

### 4:00–4:30 · Intelligence (not three hardcoded demos)

| | |
|--|--|
| **SHOW** | **Website: ◉ Dashboard** |
| **CLICK / DO** | Scroll: **hero KPIs** → **charts** → **counterfactual** panel |
| **SAY** | "And these aren't three hardcoded demos." |
| **SAY** | "Every case goes through the same control plane: **Detect. Diagnose. Score. Decide. Execute. Prove.**" |
| **SAY** | "We combine **rules** for known Razorpay failures, **classical ML** for recovery probability, and **AI** where reasoning adds value — unknown failures, personalized copy, promise-to-pay." |
| **SAY** | "And importantly — **AI doesn't independently move money**. The **policy layer** controls what's allowed." |
| **SAY** | Point at **Smart vs naive recovery** panel: "Naive strategy: remind **everyone**. Smart: chase worth-it cases, **stop** spam, **delay** on outage." |

---

# ACT 3 — PROOF + CLOSE (4:30–5:00)

### 4:30–4:50 · The money

| | |
|--|--|
| **SHOW** | **Website: ◉ Dashboard** — hero KPIs + **Recovery by category** |
| **CLICK / DO** | **Option A:** Already fired batch → scroll metrics **Option B:** **⚡ Scenarios** → **Fire all + simulate recoveries** → wait → **◉ Dashboard** |
| **SAY** | "Ultimately this isn't about how intelligent the dashboard looks. **It's about the money.**" |
| **SAY** | "Across our demo batch: **₹33,690 at risk**. **₹2,298 recovered and attributed**." |
| **SAY** | "The question isn't: how many customers did we contact?" |
| **PAUSE** | |
| **SAY** | "**The question is: how much revenue did we recover — without wasting recovery spend?**" |

| | |
|--|--|
| **SHOW** | **Slide 12–13** — proof + counterfactual *(brief)* |

---

### 4:50–5:00 · Close (face to camera)

| | |
|--|--|
| **SHOW** | **Slide 14** — closing |
| **CLICK / DO** | Full-screen slide → **look at judges** |
| **SAY** | "So Razorpay already **moves the money**." |
| **SAY** | "RevRecover decides which slipping revenue is **actually worth winning back**." |
| **PAUSE** | |
| **SAY** | "We don't chase every failed payment." |
| **SAY** | "We chase the ones who still want to pay — **and we know when to stop**." |

**Pick ONE closing tagline:**

| Option | Line |
|--------|------|
| **A — Memorable** | "**Don't chase every failed payment. Chase every payment worth saving.** — RevRecover." |
| **B — Playful** *(deck line)* | "We don't chase every failed payment like an ex who won't read the hint. We chase the ones who **want to pay** — and **stop** when they've swiped left on checkout." |
| **C — Hinglish** | "OTP galat hai toh link bhejo. Bank down hai toh **ruko**. Cancel kar diya toh **ek email**. Zyada SMS nahi. **RevRecover** — Track 03. Thank you." |

---

## Slide ↔ time ↔ website cheat sheet

| Time | Slide | Website action |
|------|-------|----------------|
| 0:00 | 2 | — (situation hook) |
| 0:15 | 3 | — (Rahul, Priya, bank) |
| 0:50 | 4 | — (merchant gap) |
| 1:20 | 6–7 | — (pipeline WOW) |
| 1:55 | — | Open **Dashboard** → go **Scenarios** |
| 2:00 | 8 flash | Fire **Wrong OTP** → **Case history** |
| 3:00 | 9 flash | Fire **Cancelled** → **Case history** |
| 3:30 | 10 flash | Fire **Bank downtime** → **Case history** |
| 4:00 | — | **Dashboard** — KPIs, charts, counterfactual |
| 4:30 | 12–13 flash | **Dashboard** — batch ₹ proof |
| 4:50 | 14 | Face — close |

---

## Website map (pitch only)

| Tab | Use for |
|-----|---------|
| **◉ Dashboard** | Hero KPIs, charts, counterfactual, recovery by category |
| **⚡ Scenarios** | Fire Wrong OTP, Cancelled, Bank downtime, Fire all + simulate |
| **◎ Case history** | DELAYED / AWAITING / STOPPED badges, journey, Demo pay |
| **💳 Checkout** | **Skip** in 5-min pitch |

---

## One-page teleprompter (lines only — print this)

**OPEN**  
Imagine 11 PM. Flash sale. ₹3 lakh expected. Dashboard says FAILED.  
Failed doesn't tell you what to do next.

Rahul — wrong OTP. Wants to pay. High intent.  
Priya — pressed back. Changed her mind. Five reminders = harassment.  
Bank down. Customer can't fix an outage.

Three payments. Three failures. Three different actions.

Razorpay gives the event. Merchants still answer: why, worth it, what to do, when to stop.  
That's RevRecover.

**WOW**  
Detect → Diagnose → Score → Decide → Execute → Prove.  
We don't optimize reminders sent. We optimize money recovered.

So instead of another dashboard — let me show you what happens when money slips away.

**DEMO**  
Rahul: incorrect_otp → CHASE → link + SMS → ₹ attributed.  
Priya: cancelled → one soft nudge → STOP if already nudged. Recover intent, not pressure.  
Bank: DELAYED. Sometimes the smartest recovery is doing nothing.

**INTELLIGENCE**  
Same control plane for every case. Rules + ML + AI where it helps. AI doesn't move money — policy does.

**PROOF**  
₹33,690 at risk. ₹2,298 recovered. Not "how many contacted" — how much recovered without wasted spend.

**CLOSE**  
Razorpay moves money. RevRecover decides what's worth winning back.  
Don't chase every failed payment. Chase every payment worth saving. Thank you.

---

## Recording workflow

1. Record **Slides 2–7** (hook + WOW) — ~2 min.  
2. Record **browser** Acts 2–3 in one take — Scenarios + Case history + Dashboard.  
3. Record **Slide 14** close on camera.  
4. Edit: hook slides → live demo → close.

---

## Related files

| File | Purpose |
|------|---------|
| `RevRecover_Pitch_Deck.pptx` | 16-slide deck |
| `scripts/generate_pitch_deck.py` | Regenerate deck |
| `DEMO_SCRIPT.md` | Shorter 2-min walkthrough |
| `PROJECT_ARCHITECTURE.md` | Technical Q&A after pitch |
