# Recording script

Roughly 4 minutes. Simple English, short lines. **Do** is what you click, **Say**
is what you speak over it.

Before you start: log out, open `localhost:3000`, close DevTools, browser at 100%.

---

## 1 · Login — 20 sec

**Do:** Type any 10-digit mobile number → Send code → type any 6 digits → Log in.

**Say:**
> This is Bhav Setu. The farmer logs in with his mobile number.
> The code comes on WhatsApp, so there is no SMS cost for him.

---

## 2 · Dashboard — 30 sec

**Do:** Show Nashik. Switch district to Pune. Click the **Fruits** tab. Click any row.

**Say:**
> This is today's price for every crop in his district.
> He can see which mandi is paying the most, and how much arrived.
> Vegetables and fruits, all in one place.

---

## 3 · Advisor — 50 sec *(the important one)*

**Do:** Onion, 80 quintal, grade B, shed → Get advice. Then change crop to **Tomato**.

**Say:**
> Now the main part. He tells us his crop, quantity and grade.
> We say: sell 40 quintal today at Lasalgaon, hold 40 for 15 days.
> That is about six thousand rupees more than selling everything today.
> Now watch — I change it to tomato. It says sell everything today.
> Because tomato rots fast, waiting costs more than the price gain.

---

## 4 · Compare — 35 sec

**Do:** Show the table. Point at **By gross** vs **By net**. Open one **Breakdown**.

**Say:**
> Every other app shows the market price. We show what reaches his hand.
> Look here — the market with the highest price is not the best one.
> After commission, cess and transport, the order changes completely.
> This is the full breakdown — every rupee that leaves his pocket.

---

## 5 · Community — 30 sec

**Do:** Show a pool card. Point at the saving. Point at the call and WhatsApp buttons.

**Say:**
> Transport is the one cost a small farmer can control.
> Four farmers going to the same mandi can share one truck.
> Alone it costs five hundred rupees. Shared, only one sixty-eight.
> He can call or message them directly from here.

---

## 6 · History — 20 sec

**Do:** Show the list. Expand one entry.

**Say:**
> Everything he has asked us is saved here.
> He can open any old advice and run it again.

---

## 7 · Chat — 45 sec

**Do:** Type `onion 80 quintal` → `Grade B` → `Shed`. Then type `POOL`.

**Say:**
> Most farmers only use WhatsApp. This is the same engine, in Marathi.
> Crop, grade, storage — and the same advice comes back.
> He can type POOL to join a shared truck.
> Later the bot asks what price he actually got, and that makes the next
> advice better for everyone.

---

## 8 · Close — 15 sec

**Do:** Switch **EN → मराठी** in the top bar.

**Say:**
> An honest forecast with a range, the real money in hand, and one clear
> decision — in his own language, on the phone he already has.

---

## Quick tips

- Speak slowly. Pause 2 seconds after each screen loads before talking.
- The two moments that win it: **tomato flipping to sell-now**, and the
  **ranking changing** on Compare. Slow down there.
- If anything looks unstyled, the dev server broke — kill node, delete `.next`,
  `npm run dev`, and record again.
