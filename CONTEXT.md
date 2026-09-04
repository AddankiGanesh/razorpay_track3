# Project Context: Razorpay Buildathon — Track 03: AI Revenue Recovery

> **Note:** This is the original planning export. For the full up-to-date picture, read **`PROJECT_CONTEXT.md`** (planning + catalog) and **`PROJECT_ARCHITECTURE.md`** (built system, APIs, AI/ML map, v0.8.2).

> Read this entire file before doing anything. This is the full context of planning done so far. Deadline: **September 2, 2026**.

---

## 1. The Track

**Track 03: AI Revenue Recovery**
Tagline: *"Find revenue that's slipping away and win it back."*

**Official description:** Build an agent that detects revenue at risk, determines the right intervention, and executes a bounded recovery workflow: from payment failures and checkout abandonment to overdue receivables.

**The judging bar (exact wording, treat as the rubric):**
> "Don't just identify the problem. Show measured money recovered across a batch, with compliant escalation, stopping rules, and an audit trail."

**Official Example Directions listed on the track page:**
- Payment degradation → root cause → recovery action
- Checkout drop-off recovery
- Failed-subscription recovery
- B2B receivables chaser
- Mandate retry sequencer
- Hinglish voice recovery
- Promise-to-pay tracker

**Important boundary:** Fraud, returns, and chargebacks belong to a DIFFERENT track (Track 02: AI Risk Manager). Do not drift into fraud-detection territory — that's out of scope here even if the data (e.g. a `payment.failed` event) looks similar.

**Submission requirements:** Public repo, 5-minute pitch video, architecture explained.

---

## 2. All Categories Identified (7 total)

| # | Category | Trigger Signal | Recovery Type |
|---|---|---|---|
| 1 | Payment failure (single transaction) | `payment.failed` webhook; error `reason`/`source`/`step` fields | Customer-facing OR system-facing, depends on cause |
| 2 | Checkout abandonment | Order created, never reaches `order.paid` | Customer-facing |
| 3 | Subscription / mandate failure | `subscription.pending` → `subscription.halted` | Customer-facing |
| 4 | Overdue receivables (B2B invoices) | Invoice/Payment Link unpaid past `expire_by` | Customer-facing |
| 5 | Authorized-but-not-captured | Payment `authorized`, capture window missed | System-facing (autonomous) |
| 6 | Suspense / reconciliation mismatch | Payment debited, not reflected merchant-side | System-facing (autonomous) |
| 7 | Suboptimal routing (bank/gateway-caused failures) | Repeated failures on same gateway/BIN combo | System-facing (autonomous) |

Categories 1, 2, 4 are explicit in the track description text. Category 3 is explicit in Example Directions. Categories 5, 6, 7 were identified through deeper research into Razorpay's docs — NOT named by the track, and are a deliberate differentiator.

---

## 3. What We're Building (Scope Decision)

### Primary build — Bundle A (fully executed, measured, demoed)
Categories **#1 (customer-caused failures) + #2 + #3 + #4**, built as ONE shared engine with four entry points/adapters. This directly mirrors the track's own language ("from payment failures and checkout abandonment... to overdue receivables").

### Secondary/bonus build — one case from Bundle B
Category **#5 (authorized-but-not-captured)** — fully autonomous, zero customer interaction, cleanest to simulate reliably in test mode (can deliberately delay/skip captures on purpose), and gives the cleanest, most unambiguous "₹ recovered" story for the demo. Almost no other team will think of this.

### Documented but not fully built
Categories **#6 and #7** — named explicitly in the pitch/README as "further opportunities we identified," with the pipeline architected so they could plug in as new adapters later. Proves scope of thinking without diluting execution. A short 3-5 sentence writeup each, optionally a small architecture stub if time allows — NOT full builds.

**Do not spread thin across all 7 fully — depth beats breadth per the judging rubric.**

---

## 4. Core Architecture (shared across all categories)

```
DETECTION (adapters) → DIAGNOSIS (classifier) → DECISION (policy) → EXECUTION (bounded) → AUDIT TRAIL (log/DB)
```

Every category is a different **adapter** feeding into the same pipeline — this is the standout architectural story: one engine, not four bolted-together demos. Make this visible in the pitch (a diagram of one core pipeline with multiple triggers feeding in), not four unrelated-looking demos back to back.

---

## 5. Deep Solution Notes Per Category

### Category 1 — Payment Failure (single transaction)
Razorpay's error object has structured fields: `code`, `description`, `source`, `step`, `reason`, `metadata`. Use `source` as the primary routing key:

| `source` | Meaning | Correct intervention |
|---|---|---|
| `customer` (wrong OTP, cancelled, insufficient funds) | Their fault | Friendly, SPECIFIC nudge referencing the actual failure reason — not a generic "payment failed" message |
| `bank` / `gateway` (downtime, technical issue) | Not their fault | Never blame the customer in messaging. Delay retry until downtime clears. This is a stopping rule. |
| Fraud-flagged decline | Bank suspects fraud | Do NOT retry same card. Suggest alternate payment method. Do not build deep fraud logic — that's Track 2's job, just route away from it. |

Bonus: track failure `reason` frequency per customer over time — if a customer fails repeatedly with `source: bank`, that's a systemic pattern worth surfacing to the merchant, not just a per-event reaction.

Card failure reasons to simulate: time-limit exceeded (~10 min), bank/partner downtime, customer cancelled/back button, bank declined as fraud.
UPI failure reasons to simulate: customer cancelled, UPI provider downtime, wrong bank account linked, partner bank technical issues.

Full downloadable Razorpay error-reasons spreadsheet (dataset backbone):
`https://razorpay.com/docs/build/browser/assets/images/payments_error_reasons.xlsx`

### Category 2 — Checkout Abandonment
No native "abandoned" webhook exists — infer it: order created, X minutes pass, no `order.paid` event fires.

Segment by likely drop-off point using timing signals:
- Order created, zero payment attempts in N minutes → dropped before choosing method (price/trust hesitation)
- Order created, a `payment.failed` fired, then silence → hit friction — nudge should reference the SPECIFIC failure ("having trouble with your card? Try UPI instead"), not a generic blast

Stopping rule (mirrors Razorpay's own Payment Links reminder design — max 3 reminders, fixed windows 11am-12pm / 3pm-5pm): cap nudges at 2-3 attempts with increasing time gaps (e.g. 1hr, 24hr, 72hr), hard-stop after. Cite this as inspiration in the pitch.

### Category 3 — Subscription / Mandate Failure (strongest differentiator)
Razorpay ALREADY auto-retries subscriptions: T=0 first charge attempt fails → `subscription.pending` → auto-retry T+1, T+2, T+3 → if still failing, `subscription.halted`. Do NOT rebuild this retry loop — it's redundant and out of your control. Build value AROUND it instead:

1. The moment `subscription.pending` fires (T=0, first failure), immediately notify the customer proactively — don't wait for all Razorpay auto-retries to exhaust. Early specific intervention recovers more than waiting.
2. Once `subscription.halted` fires: invoices keep generating with NO auto-charge ever attempted again — this is where merchants silently bleed money forever. Build a "halted subscription revival" job: periodically check halted subscriptions, and if the customer updated their card (e.g. via Razorpay's email link), trigger a manual charge attempt via API immediately rather than waiting.
3. Demo story: "X% of halted subscriptions in our batch revived within 48 hours vs. Razorpay's default of zero automatic revival."

Key webhooks: `subscription.pending`, `subscription.halted`, `subscription.charged`, `subscription.activated`.

### Category 4 — Overdue Receivables (B2B)
Razorpay's native invoice reminders are generic/fixed (same 3-reminder cadence for everyone, sent only in windows 11am-12pm/3pm-5pm). Beat this with:
- Tiered escalation: reminder 1 soft (email) → reminder 2 firmer (SMS+email) → reminder 3 "final notice" + optional early-payment discount → after 3, escalate to human-flagged list. Never exceed 3 automated reminders — matches Razorpay's own cap, is your compliant stopping rule.
- Promise-to-pay tracker (explicitly in track's Example Directions): if customer replies "I'll pay by Friday," log the promise, suppress further automated reminders until Friday, resume escalation only if missed. Shows non-annoying, nuanced automation.

Invoice/Payment Link fields to track: `amount`, `amount_paid`, `expire_by`, `status` (`created`/`paid`/`partially_paid`/`expired`/`cancelled`).

### Category 5 — Authorized-but-Not-Captured (bonus differentiator)
Razorpay flow: authorize → merchant must explicitly call capture within a window → if merchant's system fails to capture in time, the authorization auto-reverses and money already taken from customer goes back to them. Pure operational leak, zero customer interaction needed, zero ambiguity about cause.

Build:
1. Detect: listen for `payment.authorized` events
2. Diagnose: check if a capture call happened within a safety margin (e.g. within 2 minutes)
3. Decide: if no capture detected — always act, not ambiguous
4. Execute: fire the capture API call automatically
5. Audit: log "auto-captured payment X, would have reverted ₹Y"

This is the cleanest "measured money recovered" story — you can deliberately engineer failures in test mode (delay/skip captures on purpose on some synthetic transactions) and show a clean, provable before/after ₹ number.

### Category 6 — Suspense/Reconciliation Mismatch (documented only)
Payment debited from customer, stuck in a suspense account due to bank/network handoff failure. Detection adapter could plug in: verify payment status via API at intervals; if customer-debited-but-merchant-side-missing beyond a threshold, flag for reconciliation (NOT retry — retrying would double-charge).

### Category 7 — Suboptimal Routing (documented only)
Pattern-detect repeated failures for the same BIN/card-type/amount-bracket on one gateway path. Fix isn't a retry — it's flagging "this segment needs multi-terminal routing," a merchant-facing insight rather than a customer-facing action.

---

## 6. Voice Recovery (differentiator — explicitly track-endorsed via "Hinglish voice recovery")

Very few teams will attempt this because it's harder to build than a text nudge — high standout value if pulled off.

**Where to use voice** (reserve for high-value/high-friction cases, not everywhere):
- Halted subscriptions — a call recovers better than a 4th unread email
- B2B receivables, final escalation tier — after 2 automated reminders go unanswered, before/instead of a "final notice"

**Build approach — sequence by risk:**
1. **Fastest, build first:** Twilio Voice API + pre-scripted text-to-speech call (NOT live conversational). E.g. "This is an automated call from [merchant]. Your payment of ₹X failed. Press 1 to retry, press 2 to speak to support." Achievable in hours.
2. **More impressive, riskier, only if time allows:** real conversational voice agent (speech-to-text → LLM → text-to-speech, or a turnkey platform like Vapi/Bland/Retell) responding in Hinglish. Meaningfully more build time, more can break live in a demo.

**Recommendation:** build the scripted/IVR version first and get it solid. Only attempt conversational version with genuine time margin left. Working simple beats broken ambitious, especially live on demo day.

---

## 7. Notification Channels — Build Priority (fastest to slowest to get working)
1. **Email** — fastest, any free SMTP service or Resend, no approval process
2. **SMS** — Twilio trial account, works immediately for test numbers
3. **WhatsApp** — most "on-brand" for Indian merchants but requires Meta Business API approval (can take longer than the buildathon window) — MOCK this (log "would send WhatsApp: [message]") rather than chasing real approval
4. **Voice** — the standout differentiator (see section 6)

---

## 8. Simulation / Demo Layer

**Do NOT build a full e-commerce storefront.** Razorpay isn't judging web design — the agent's intelligence and recovery pipeline is what's scored.

**Two components needed:**
1. **Synthetic data generator (primary, most important):** a script using Razorpay's API/SDK directly to programmatically create ~50-100+ orders/payments/subscriptions/invoices with varied `reason` codes and timings. This is the real dataset for the "measured across a batch" requirement. No webpage needed for this.
2. **Minimal Checkout.js page (optional, demo polish only):** one bare-bones HTML page with Razorpay's standard Checkout.js embed, a fixed test amount. Purpose: one real, live, human-clicking-a-button moment for the pitch video, for credibility/trust — not a functional requirement. Should take a few hours max, not a project. Build this LAST, only if time remains.

---

## 9. Technical Setup

- **Test mode dashboard:** dashboard.razorpay.com/app/payments (Test Mode toggle in sidebar)
- **Getting test API keys:** Account & Settings → API Keys, OR use the "Get Test API Keys" shortcut in the onboarding sidebar to bypass full KYC/live-business onboarding (which is NOT needed for test mode — only for real/live payments)
- If onboarding forces a website link: use "Add later," or select "Unregistered" business type for minimal required fields, or use a placeholder link (e.g. GitHub repo URL)
- **SDK:** pick Node.js or Python (razorpay-node or razorpay-python), whichever is faster for the builder
- **Key webhooks to subscribe to:** `payment.failed`, `payment.authorized`, `order.paid`, `subscription.pending`, `subscription.halted`, `subscription.charged`, `payment_link.paid`, `payment_link.expired`
- **Local webhook testing:** use ngrok to expose a local server for Razorpay's webhook calls during development
- **Reference docs:**
  - Error codes structure: razorpay.com/docs/errors/error-reasons
  - Card error codes: razorpay.com/docs/errors/payments/cards/
  - UPI error codes: razorpay.com/docs/errors/payments/upi/
  - Subscription retry logic: razorpay.com/docs/subscriptions/handling-retries
  - Subscription states: razorpay.com/docs/payments/subscriptions/states/
  - Payments webhooks: razorpay.com/docs/webhooks/payments/
  - Payment Links webhooks: razorpay.com/docs/webhooks/payment-links/
  - Invoices API: razorpay.com/docs/api/payments/invoices/

---

## 10. Build Timeline (7 days, deadline Sep 2, 2026)

- **Day 1:** Finish Razorpay test-mode setup, project repo scaffolding, pick language/SDK, write synthetic dataset generator script (50-100+ cases, varied `reason` codes)
- **Day 2:** Webhook receiver (via ngrok), detection adapters for the 4 Bundle A categories
- **Day 3:** Diagnosis layer (classify by `source`/`step`/`reason`), decision/policy logic, execution layer (email + SMS real, WhatsApp mocked), audit trail logging (structured JSON per action)
- **Day 4:** Voice differentiator — Twilio Voice API, scripted/IVR call for one high-value case (halted subscription revival works well)
- **Day 5:** Bonus category #5 (authorized-but-not-captured), fix whatever broke in days 1-4
- **Day 6:** Minimal Checkout.js demo page, metrics dashboard (₹ recovered / ₹ at risk, batch results, recovery rate by category), run full batch test for real numbers
- **Day 7 (buffer):** Record 5-minute pitch video, write README/architecture doc, push public repo. Keep this day free of new features — fixes and polish only.

**Golden rule: don't start later-day work early just because ahead of schedule.** If time frees up, harden what's built (more edge cases, better audit detail) rather than adding new scope — hackathon time pressure usually comes from scope creep, not slow progress.

---

## 11. Why This Plan Stands Out (for the pitch narrative)

1. One real shared engine (detect/diagnose/decide/execute/log), not four separate demos — adapters per category
2. Root-cause-aware routing using Razorpay's own `source`/`step`/`reason` taxonomy, not blanket retry-everything logic
3. A genuinely novel category (#5, authorized-not-captured) with the cleanest, most provable recovered-₹ story — nobody else will likely build this
4. Explicit stopping rules borrowed from Razorpay's OWN product decisions (3-reminder cap, fixed send windows) — shows deep docs research, not invented rules
5. Voice recovery — track-endorsed via Example Directions, but high-effort so most teams will skip it
6. A scoped, honest "further opportunities" section (#6, #7) that proves breadth of thinking without over-promising or diluting execution
7. Must avoid drifting into fraud/chargeback territory — that's Track 2, not this track

---

## 12. Immediate Next Step

Start with **Day 1 task**: write the synthetic dataset generator script. This creates ~50-100 test payment/order/subscription/invoice records via the Razorpay API with varied failure `reason` codes and realistic timing patterns — the foundation dataset for everything downstream (detection, diagnosis testing, and the final "measured across a batch" metrics requirement).
