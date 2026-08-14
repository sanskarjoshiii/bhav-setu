# User flow

Two ways in — the website and WhatsApp — and they meet at the same decision engine.
This page traces what a farmer actually does, screen by screen.

---

## 1. The main journey

```mermaid
flowchart TD
    START([Farmer arrives]) --> LAND[Home<br/><i>live price + forecast band</i>]

    LAND --> AUTH{Has an<br/>account?}
    AUTH -->|No| SIGNUP[Sign up<br/><i>3 steps: name · village · risk</i>]
    AUTH -->|Yes| LOGIN[Log in<br/><i>mobile → OTP on WhatsApp</i>]

    SIGNUP --> DASH
    LOGIN --> DASH[Dashboard<br/><i>today's prices for his district</i>]

    DASH --> PICK{What does<br/>he want?}

    PICK -->|Check a price| BROWSE[Filter by district<br/>Vegetables · Fruits · Today]
    PICK -->|Decide on a lot| ADVISOR[Advisor]
    PICK -->|Compare markets| COMPARE[Mandi Compare]
    PICK -->|Cut transport cost| POOL[Community]

    BROWSE --> ADVISOR

    ADVISOR --> LOT[Enter the lot<br/><i>crop · quantity · grade<br/>storage · risk appetite</i>]
    LOT --> ENGINE[[Decision engine<br/>scores every plan]]
    ENGINE --> REC[Recommendation<br/><b>sell 40 today at Lasalgaon</b><br/><b>hold 40 for 15 days</b><br/><i>+ reason · confidence · ₹ gain</i>]

    REC --> SAVED[(Saved to History<br/>automatically)]
    REC --> ACT{What now?}

    COMPARE --> FLIP[Rank by gross<br/>vs rank by net<br/><i>the order changes</i>]
    FLIP --> WATERFALL[Open a breakdown<br/><i>every rupee that leaves</i>]
    WATERFALL --> ACT

    POOL --> JOIN[Join a truck<br/><i>₹504 alone → ₹168 split</i>]
    JOIN --> CALL[Call or WhatsApp<br/>the other farmers]
    CALL --> ACT

    ACT -->|Sell| SELL([Takes the lot to the mandi])
    ACT -->|Ask in Marathi| WA[Continue on WhatsApp]
    ACT -->|Review later| HIST[History<br/><i>every past search</i>]

    HIST -->|Run it again| ADVISOR
    WA --> BOT[Bot conversation]
    BOT --> REC

    SELL --> REPORT[/"What price did<br/>you actually get?"/]
    REPORT --> FEEDBACK[(Sale report stored)]
    FEEDBACK --> SCORE[Transparency score<br/>for that mandi]
    SCORE -.->|makes the next<br/>recommendation better| ENGINE

    classDef entry fill:#EDEDE1,stroke:#C3C3B4,color:#16160F
    classDef screen fill:#FFFFFF,stroke:#16160F,color:#16160F
    classDef core fill:#1F3D2B,stroke:#1F3D2B,color:#F3F3EA
    classDef loop fill:#16160F,stroke:#16160F,color:#F3F3EA

    class START,LAND,AUTH entry
    class DASH,ADVISOR,COMPARE,POOL,BROWSE,LOT,FLIP,WATERFALL,JOIN,CALL,HIST screen
    class ENGINE,REC core
    class REPORT,FEEDBACK,SCORE,SAVED loop
```

The dotted line at the bottom is the part that matters commercially: **what the
farmer was really paid feeds back into the next recommendation.**

---

## 2. WhatsApp conversation

The bot is a state machine. Every step offers quick-reply buttons, so a farmer on
a ₹4,000 phone never has to type more than a number.

```mermaid
stateDiagram-v2
    [*] --> GREETING

    GREETING: Namaskar 🙏<br/>Which crop, how many quintals?
    AWAITING_CROP: "onion 80 quintal"
    AWAITING_GRADE: Which grade?<br/>A · B · C
    AWAITING_STORAGE: Where is it stored?<br/>Shed · Open · Cold store
    ADVICE_GIVEN: The plan<br/>+ reason + confidence + ₹ gain<br/>+ shared-truck nudge
    AWAITING_SALE: What price did you<br/>actually get?
    RECORDED: Thank you —<br/>it is on your History page
    POOL_INFO: Truck to Lasalgaon<br/>tomorrow 5:30 AM<br/>₹504 alone → ₹168 split

    GREETING --> AWAITING_CROP: farmer replies
    AWAITING_CROP --> AWAITING_GRADE
    AWAITING_GRADE --> AWAITING_STORAGE
    AWAITING_STORAGE --> ADVICE_GIVEN
    ADVICE_GIVEN --> AWAITING_SALE: "I sold today"
    AWAITING_SALE --> RECORDED: types a price
    RECORDED --> AWAITING_CROP: "another lot"

    ADVICE_GIVEN --> POOL_INFO: types POOL
    POOL_INFO --> AWAITING_SALE

    GREETING --> POOL_INFO: POOL works anywhere
    AWAITING_CROP --> GREETING: unrecognised → help
```

`POOL` is recognised at any point in the conversation, and anything the bot cannot
parse returns a help message with buttons rather than a dead end.

---

## 3. What each screen is for

| Screen | The farmer's question | What he leaves with |
|---|---|---|
| **Home** | Is this worth my time? | A live price and an honest forecast band |
| **Dashboard** | What is my district paying today? | Every crop, best mandi per crop, arrivals |
| **Advisor** | What do I do with *this* lot? | Sell/hold split, in rupees, with a reason |
| **Compare** | Which mandi should I drive to? | Net ranking — often not the highest price |
| **Community** | Can I cut my transport cost? | A truck to share, and numbers to call |
| **History** | What did they tell me last time? | Every past search, re-runnable |
| **Chat** | Can I just ask in Marathi? | The same plan, in a conversation |

---

## 4. The three decisions that shape every screen

**A range, never a single number.** Every forecast is P10–P50–P90. Nobody can
predict onion to the rupee, and pretending otherwise is how a farmer with a loan
gets ruined. When the band is too wide, the system says so and pushes toward
selling today.

**Net in hand, never the board price.** Commission, cess, hamali, weighing,
packing, road distance, storage, interest and spoilage all come out before any
number is shown. `net_per_qtl` is divided by the *original* quantity, so anything
that rots during a hold shows up as a lower rate rather than hiding in a total.

**Hard rules override the maths.** Six constraints sit above the optimiser: never
hold past a crop's shelf life, never hold through a spoilage cliff, never send a
tiny lot ninety kilometres, and if the government just banned exports, sell today
and do not argue.

---

## 5. Recording walkthrough

The path that shows the most in the least time:

1. **Log in** — mobile number, then the code
2. **Dashboard** — switch district, switch to Fruits, click a row to change the chart
3. **Advisor** — start on onion (a split with a rupee gain), switch to tomato and
   watch it flip to sell-now because tomato spoils
4. **Compare** — change the crop, open a Breakdown, point at the rank flip
5. **Community** — the ₹504 → ₹168 saving, and the call buttons
6. **History** — the searches from steps 3 and 4 are already listed
7. **Chat** — run the flow, then type `POOL`
8. **EN → मराठी** — the toggle works throughout
