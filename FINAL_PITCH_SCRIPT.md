# RevRecover — Final Pitch Script (Simple Story)

**Deck:** `RevRecover_Beautiful_Pitch_Deck.pptx` (14 slides)  
**Time:** ~5 minutes · Talk slowly · Pause after big lines  
**Website:** `http://127.0.0.1:8001/` after `python -m app.run`

**Before pitch:** Reset demo once · Email: `ganeshsuraj29@gmail.com`

---

# THE STORY (say it like you're talking to one person)

---

## SLIDE 1 — Who we are

**[SHOW: Slide 1]**

> Hi. We built **RevRecover**.
>
> Simple idea: when a payment fails, money is **slipping away**. We help the merchant **spot it**, **decide if it's worth saving**, and **bring that money back**.
>
> We do it in five steps — **Detect, Diagnose, Decide, Execute, and Prove.**
>
> Let me walk you through **why** we needed this.

*(next slide)*

---

## SLIDE 2 — The problem starts at 11 PM

**[SHOW: Slide 2]**

> So imagine **11 PM**.
>
> Your flash sale just finished. You were expecting **₹3 lakh** tonight.
>
> You open the dashboard… and it says **FAILED**.
>
> Now here's the twist — **three customers** failed that night. Same word: **FAILED**. But **three totally different stories.**
>
> One customer typed the **wrong OTP** — he still wants to pay.
> One customer **pressed back** — she changed her mind.
> One customer tried to pay but the **bank was down**.
>
> If you send the same **"please try again"** message to all three…
> you **annoy** the girl who left,
> you **waste money** on the bank outage,
> and you might still **lose** the guy who was ready to pay.
>
> **That's the problem we started with.**

*(next slide)*

---

## SLIDE 3 — Razorpay gives the signal. Someone still has to decide.

**[SHOW: Slide 3]**

> Now — **Razorpay already does a lot.**
>
> You get the webhook. Payment failed. Subscription halted. Payment links. Retries. APIs. All of that is there.
>
> **Razorpay moves the money.**
>
> But after a failure, the merchant is still stuck asking:
>
> *Why* did this fail?
> *Should I* even follow up?
> *How* should I follow up — SMS, email, or wait?
> And *when do I stop* before I spam the customer?
>
> And at the end — *did we actually get the money back?*
>
> **Nobody was answering those questions in one place.**
>
> So we built **RevRecover** — the layer that sits **on top of Razorpay** and makes those decisions for you.

*(next slide)*

---

## SLIDE 4 — The money doesn't disappear in one moment

**[SHOW: Slide 4]**

> And it's not just one failed checkout.
>
> Money leaks in **many quiet ways.**
>
> A **B2B payment link expires.**
> A **subscription stops** charging.
> Someone **drops off** at checkout.
>
> The money doesn't shout when it's leaving. **It just quietly goes.**

*(next slide)*

---

## SLIDE 5 — So we built RevRecover

**[SHOW: Slide 5]**

> That's why we built **RevRecover.**
>
> It's **not** another bot that sends reminders to everyone.
>
> It's a **revenue operator** — it looks at each failure and asks: *is this worth chasing?*
>
> We map **110+ failure reasons** from Razorpay.
> We give each case a **score** — how likely is recovery?
> We check **how much money** we can realistically get back.
> And we check **ROI** — is it worth spending on SMS or email?
>
> **Smart decisions. Not blind reminders.**

*(next slide)*

---

## SLIDE 6 — Every case follows the same path

**[SHOW: Slide 6]**

> Every case goes through the **same five steps** you saw on slide one —
> but the **action changes** depending on the failure.
>
> **Detect** — we catch the event.
> **Diagnose** — we read the failure reason.
> **Decide** — score + rules: chase, stop, delay, or watch.
> **Execute** — send the right message on the right channel.
> **Prove** — when they pay, we record **exactly which action recovered the money.**
>
> And we keep it **safe** — limits on retries, pause during bank outage, human handoff for big B2B deals, full audit trail.
>
> **The AI suggests. The rules decide. Money doesn't move on its own.**
>
> Okay — enough talk. **Let me show you live.**

*(open browser → ⚡ Scenarios · keep Slide 7 ready)*

---

## SLIDE 7 — Story 1: Wrong OTP → Chase him

**[SHOW: Slide 7 + ⚡ Scenarios → Wrong OTP → Fire → ◎ Case history]**

> Remember the customer who typed the **wrong OTP**?
>
> Razorpay tells us: wrong OTP. **He wants to pay.** High intent.
>
> So RevRecover says: **RETRY.**
> Send urgent SMS. Send a fresh payment link. Chase it now.
>
> ** [SHOW: Demo pay → Simulate → ◉ Dashboard — point Recovered ₹] **
>
> When he pays, we don't just say "success." We **link that ₹ back to this exact action.**
>
> As the slide says —
> **Razorpay tells you something is wrong. RevRecover tells you what to do about it.**

*(next slide)*

---

## SLIDE 8 — Story 2: She cancelled → Don't spam her

**[SHOW: Slide 8 + ⚡ Fire Customer cancelled → ◎ Case history]**

> Now remember the customer who **pressed back**?
>
> Same checkout. **Opposite situation.**
>
> She cancelled. She changed her mind.
>
> RevRecover does **not** chase her with five SMS messages.
>
> **One soft email. That's it.**
> Already nudged her before? **STOP.**
>
> We protect the customer — and we protect the brand.
>
> **Recover people who want to pay. Don't pressure people who don't.**

*(next slide)*

---

## SLIDE 9 — Story 3: Bank down → Wait, don't chase

**[SHOW: Slide 9 + ⚡ Fire Bank downtime → ◎ Case history → DELAYED]**

> Third customer — **bank was down.**
>
> The customer **cannot fix that.** So why send them angry reminders?
>
> RevRecover marks it **DELAYED.**
> No SMS. No email during the outage.
> We wait. We retry when the bank is back.
>
> **Sometimes the best thing to do… is wait.**
>
> That's still a smart recovery decision.

*(next slide)*

---

## SLIDE 10 — We handle more than just checkout failures

**[SHOW: Slide 10 + ◉ Dashboard — optional: escalation queue]**

> So those were three stories. But RevRecover handles **much more.**
>
> **Subscription stopped?** — voice call, Hinglish IVR, promise-to-pay.
> **Mandate declined?** — SMS, then email, then re-register — then stop.
> **Payment still pending?** — we **watch** it. No spam while it's authorizing.
> **Big B2B link expired?** — new link + **human escalation** for the account manager.
>
> **14 scenarios** in our lab — all mapped to Razorpay's real error types.
>
> **One system. Many ways money slips. One smart operator handling all of it.**

*(next slide)*

---

## SLIDE 11 — Show me the money

**[SHOW: Slide 11 + ◉ Dashboard — At risk · Recovered · Rate]**

> Now the most important part.
>
> Judges shouldn't just see fancy AI text. They should see **money coming back.**
>
> ** [Point at your dashboard — say the real numbers on screen] **
>
> "Right now we have **₹[X] at risk**… and **₹[Y] recovered**."
>
> And we know **which action, which channel, which case** brought each rupee back.
>
> **That's proof. Not a guess.**

*(next slide)*

---

## SLIDE 12 — Why this beats "remind everyone"

**[SHOW: Slide 12]**

> Same pool of failed payments.
>
> But **better choices** — so you spend less and recover smarter.
>
> We don't count how many reminders we sent.
>
> **We count how much money came back for every rupee we spent trying.**

*(next slide)*

---

## SLIDE 13 — You can trust every action

**[SHOW: Slide 13]**

> And every step is **clear and safe.**
>
> **Explain** — why this customer, why this channel, why now.
> **Bound** — limits on retries and nudges. Pause during outages.
> **Escalate** — big B2B deals go to a human.
> **Prove** — payment success is logged. No double counting.
>
> Example on the slide:
> **₹499 failed on wrong OTP → we sent a new link → customer paid → ₹499 recovered. Full trail.**

*(next slide)*

---

## SLIDE 14 — Thank you

**[SHOW: Slide 14 — look at judges]**

> So to close —
>
> **Razorpay shows you money at risk.**
> **RevRecover shows you money you can still win — and money you already won.**
>
> We don't chase every failed payment.
> We chase the ones who **still want to pay.**
> We **stop** when they don't.
> We **wait** when the bank is down.
> And we **prove** every rupee recovered.
>
> **Chase high intent. Stop spam. Delay outages. Prove the money.**
>
> That's **RevRecover.** Thank you.

---

## How slides connect (one line each)

| From → To | Link sentence |
|-----------|---------------|
| 1 → 2 | "Let me show you **why** we needed this." |
| 2 → 3 | "**That's the problem.** Razorpay gives the signal — but **someone still has to decide.**" |
| 3 → 4 | "And it's **not just one checkout failure**…" |
| 4 → 5 | "**That's why** we built RevRecover." |
| 5 → 6 | "Here's **how** it works, step by step." |
| 6 → 7 | "Okay — **let me show you** those three customers live." |
| 7 → 8 | "Same night. **Next customer — totally different.**" |
| 8 → 9 | "And the **third one** — the bank." |
| 9 → 10 | "Three stories — but we handle **even more than that.**" |
| 10 → 11 | "Pretty — but judges want to see **money.**" |
| 11 → 12 | "And this works **better than blasting everyone.**" |
| 12 → 13 | "And you can **trust** every action." |
| 13 → 14 | "So here's where we land." |

---

## Website — when to click

| Slide | Click |
|-------|-------|
| 7 | ⚡ Wrong OTP → Fire → ◎ row → Demo pay → Simulate |
| 8 | ⚡ Customer cancelled → Fire → ◎ row |
| 9 | ⚡ Bank downtime → Fire → ◎ row (DELAYED) |
| 10 | ◉ Dashboard (optional) |
| 11 | ◉ Dashboard — read At risk / Recovered |

---

## Teleprompter (print on phone)

```
S1: RevRecover. Money slips → spot it, decide, win it back. Five steps.

S2: 11 PM. ₹3L expected. FAILED. Wrong OTP / cancelled / bank down.
Same message to all three = annoy + waste + lose ready buyer.

S3: Razorpay moves money. Merchant still asks why, how, when to stop, did we recover?
RevRecover = decision layer on top.

S4: Money leaks quietly — B2B link, sub stopped, checkout drop.

S5: Not reminder bot. Revenue operator. 110+ reasons, score, worth it?, ROI.

S6: Same 5 steps, different action each time. AI suggests, rules decide. Show live.

S7: Wrong OTP → RETRY → link + SMS → ₹ linked to action. Thermometer vs doctor.

S8: Cancelled → one email → STOP. Don't pressure who doesn't want to pay.

S9: Bank down → DELAY → wait. Best move is sometimes wait.

S10: Subs, mandate, late auth, B2B. 14 scenarios. One operator.

S11: ₹[X] at risk, ₹[Y] back. Which action caused it. Proof.

S12: Not reminders sent — money back per rupee spent.

S13: Explain, bound, escalate, prove. ₹499 example on slide.

S14: Razorpay = risk. We = win back + won. Chase / Stop / Delay / Prove. Thanks.
```

---

*Practice: read out loud 3 times. Slide 1–6 = 2 min. Demo = 2 min. Slide 10–14 = 1 min.*
