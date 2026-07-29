# Investor Q&A Prep — Trade Desk

Prep for the investor demo. Answers are demo-room length (say them in 2–4
sentences). **Fill in every `[bracketed]` placeholder with your real numbers
before the meeting** — the metrics/ask are the only gaps; the product and
narrative are ready.

> Not legal or financial advice. The regulatory framing below needs validation
> by securities counsel — do not present it as settled law in the room.

---

## Part 1 — Question bank (by category)

### A. Business model & unit economics

**"How do you make money?"**
> "Three recurring streams: monthly combine subscriptions ($109 / $159 / $209
> for 50K / 100K / 150K), reset fees when a trader blows an eval and restarts,
> and activation fees on funded accounts. It's SaaS-like — a trader pays every
> month they're evaluating, and many reset multiple times."

**"What's a customer worth?"** *(needs your real data)*
> LTV = monthly sub × avg months active + reset fees; CAC = your channel cost.
> Have a real number or a credible cohort model. If early: "here's the cohort
> we're seeing" — never a fabricated figure.

**"Isn't your business just profiting from traders failing?"** ⚠️
> "The revenue is the subscription, not the failure — like a gym or a bootcamp,
> people pay to improve whether or not they pass. That's why we built the
> journal, analytics, and discipline tooling: a trader who's learning renews; a
> frustrated one churns. Our incentive is retention."

### B. Regulatory & legal ⚠️ *(hardest section — get securities counsel)*

**"Is this regulated? Is it securities trading / are you a broker-dealer?"**
> "The capital is simulated — a paper-execution environment, no customer funds
> deposited, no real orders on an exchange. The funded relationship is an
> independent-contractor performance agreement, not a brokerage account — the
> same structure as futures prop firms like Topstep. We're working with
> securities counsel on exact classification."

**"MyForexFunds got shut down; FTMO left the US. Why are you safe?"** ⚠️
> "It's the risk I lose the most sleep over. That enforcement hit firms that
> misrepresented real capital and ran deceptive payouts. Our defenses are the
> opposite: simulated capital stated plainly in the signed agreement, payouts
> through KYC + tax + human review, everything audited. I won't say it's zero
> risk — it's evolving — but it's structured deliberately and monitored with
> counsel." **Never claim you're "definitely fine."**

**"What stops you from just not paying out?"**
> "Payouts run through a real desk — KYC, tax profile, payout method, audited
> approval queue. Reputation is the entire moat here; firms that stiff traders
> die on social media in a week."

### C. Market & competition

**"Topstep / Apex / FTMO already exist. Why you?"**
> "Those are futures and forex. Options — especially 0DTE — is the
> fastest-growing retail segment and has no serious prop firm. Our wedge is
> execution: the only place you draw the option on the chart and watch the
> breakeven walk in real time as theta decays."

**"What's the moat — can't Topstep add options tomorrow?"**
> "The honest moat is distribution and trust, not code — payout reputation is
> everything in this category, and we're building the trader habit and track
> record now. First mover with the better product in options is a real lead."

### D. Product & tech

**"What's built vs. vision?"**
> "Live today: the full eval engine (trailing max-loss, daily loss limit,
> consistency rule), the visual 0DTE terminal on live market data, automatic
> journal + analytics, funded-account activation, and a complete operator back
> office — payouts, KYC, firm-wide kill switch, audit log. You saw it all run."

**"Is the trading real?"**
> "Execution is paper against live market prices — real quotes, real risk rules,
> simulated fills. The trader's skill and P&L are real; the capital is
> simulated. That's the prop-firm model."

### E. Costs & infrastructure

**"Data/infra costs — do they scale with users?"**
> "Market data is the main variable cost — on Alpaca today, with request
> budgeting and caching so a warm cache serves many traders per API call.
> Compute is light. Options-data licensing is the line item that grows with
> scale and the one to plan for."

### F. Firm risk & sustainability

**"If a trader passes and you pay them, do you lose money on winners?"**
> "No market exposure — payouts come from subscription and eval revenue, not a
> live trading book. The model works when eval + subscription revenue exceeds
> payouts + costs, which we control by calibrating the rules, not something the
> market can blow up."

**"What if everyone passes?"** ⚠️
> "The rules are calibrated so passing is achievable but requires genuine
> consistency — target, trailing drawdown, and a consistency rule that blocks
> one-lucky-day passes. We watch pass rate by tier in the operator console and
> tune it. Too easy is a revenue problem; too hard is churn — we manage the
> balance with data."

### G. Traction / GTM / team / the ask *(your real data — cannot be faked)*

Have crisp, truthful answers ready for:
- **Traction:** users, MRR, pass rate, retention/reset rate, payout volume.
  Show the operator-console metrics live if real.
- **GTM:** how you acquire options traders (FinTwit, Discord, YouTube
  educators, paid).
- **Team:** who's building it, why you.
- **The ask:** how much, what it buys (12–18 mo runway to what milestone), use
  of funds — **include a legal/compliance line item.**

### Three honesty rules for the room
1. **Regulatory:** never "we're definitely fine" — "structured carefully,
   working with counsel." Overconfidence loses a sharp investor.
2. **Numbers you don't have:** "we're pre-that, here's the plan" beats a
   fabricated figure that unravels in diligence.
3. **"Profit from failure":** reframe to retention/education; don't get
   defensive.

---

## Part 2 — Mock session (skeptical investor, worked answers)

*"Dana," fintech seed partner, looking for reasons to lean in or pass. Study
the founder lines; the `[COACH]` notes say why they land.*

**Dana:** "One sentence — what is this and how do you make money?"
**Founder:** "A prop firm for options traders — people pay a monthly fee to
prove they can trade under real risk rules, and we fund the ones who pass.
Recurring revenue: eval subscriptions, resets, activation fees. Topstep, but for
0DTE options, with execution you do on the chart."
> `[COACH]` Anchors to a known model + names the wedge in eight words. Stop
> there; let them pull.

**Dana:** "Topstep/Apex/FTMO are bigger. Why win — and what stops Topstep adding
options next quarter?"
**Founder:** "They're futures and forex; options prop is wide open and options
is where retail volume is exploding. Moat is a visual-execution engine that's
hard to build and, honestly, distribution and trust in a payout-reputation
business."
**Dana:** *(cuts in)* "'Hard to build' is what every founder says."
**Founder:** "Fair — the durable moat is distribution and trust, not code.
We're building the habit and payout track record now; that compounds."
> `[COACH]` When they call out a weak moat claim, concede and redirect to the
> real one. Fighting on "our tech is hard" loses.

**Dana:** "CFTC shut down MyForexFunds; FTMO left the US. Why aren't you a
lawsuit waiting to happen?"
**Founder:** "The risk I lose the most sleep over, so I'll be straight. That
enforcement hit firms that misrepresented real capital and ran deceptive
payouts. Ours is the opposite: capital is simulated and we say so in the signed
agreement, no customer funds deposited, payouts through KYC + tax + human
review, all audited. Working with securities counsel on classification. Not zero
risk — it's evolving — but structured deliberately and monitored."
> `[COACH]` The answer that wins or loses the room. Candor first, distinguish
> from the bad actors *specifically*, list concrete defenses, refuse to
> overclaim. Naming the risk builds more trust than waving it off.

**Dana:** "Isn't this just profiting when traders lose?"
**Founder:** "Revenue is the subscription, not the loss — like a bootcamp or a
gym. That's why we over-invested in the journal, mistake-tagging, analytics: a
trader who feels they're improving renews; a frustrated one churns. Our
incentive is retention."
> `[COACH]` Reframe failure → retention/education; point at the product as
> evidence of aligned incentives — you can show it.

**Dana:** "Capital's simulated — where does a payout come from? Market
exposure?"
**Founder:** "No market exposure — that's the point. Payouts come from
subscription and eval revenue, not a live book. Works when revenue exceeds
payouts + costs, a dial we control via rule calibration, not market risk. We
watch pass rate by tier and tune it."
> `[COACH]` Turns the scariest question into a strength: "no market risk,
> tunable-margin business."

**Dana:** "Numbers. Users, MRR, pass rate, retention. Go."
**Founder:** "[X] traders, $[Y] MRR, [Z]% pass rate, [W]% month-2 retention,
$[P] paid out. Happy to pull it up live in the operator console."
> `[COACH]` ⚠️ Cannot be faked — insert real figures. If a metric is ugly, give
> the number + trend; never dodge. Offering to show it live signals real data.

**Dana:** "What are you raising and what does it buy?"
**Founder:** "$[amount] for [N] months to [milestone]. Engineering + a
compliance/legal budget + acquisition."
> `[COACH]` A legal/compliance line item — right after the regulatory question —
> quietly signals you take the risk seriously. Strong close.

### Debrief
The session hinges on three moments: the **regulatory** answer (candor +
specifics > bravado), the **profit-from-failure** reframe, and having **real
numbers**. Everything else is easy points. Homework before the meeting: fill in
the bracketed metrics and the ask.
