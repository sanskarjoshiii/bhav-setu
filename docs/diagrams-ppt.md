# Slide diagrams

Cut-down versions of the diagrams in [architecture.md](architecture.md) and
[user-flow.md](user-flow.md), sized for a 16:9 slide. All left-to-right, under
eight boxes each, no nested subgraphs — they stay readable when shrunk.

To get an image: open this file in VS Code (Ctrl+Shift+V) or on GitHub, then
screenshot the rendered diagram.

---

## 1. Architecture

```mermaid
graph LR
    A["📥 Data<br/>Agmarknet · CEDA<br/>Weather · Policy"] --> B["🧹 Clean<br/>resolve names<br/>flag gaps"]
    B --> C["📈 Forecast<br/>LightGBM<br/>P10 · P50 · P90"]
    C --> D["💰 Net In-Hand<br/>fees · transport<br/>spoilage"]
    D --> E["🎯 Decide<br/>sell / hold / split"]
    E --> F["👨‍🌾 Farmer<br/>Web · WhatsApp"]
    F -.->|"price he<br/>actually got"| B

    classDef s fill:#EDEDE1,stroke:#8A8A7A,color:#16160F
    classDef m fill:#1F3D2B,stroke:#1F3D2B,color:#FFFFFF
    classDef o fill:#16160F,stroke:#16160F,color:#FFFFFF
    class A,B s
    class C,D,E m
    class F o
```

**One line for the slide:** raw prices in, one actionable sentence out — and what
he was really paid flows back in.

---

## 2. User flow

```mermaid
graph LR
    A["Log in"] --> B["Dashboard<br/><i>today's prices</i>"]
    B --> C["Advisor<br/><i>crop · qty · grade</i>"]
    C --> D["Plan<br/><b>sell 40 today<br/>hold 40</b>"]
    D --> E["Compare<br/><i>net beats gross</i>"]
    E --> F["Community<br/><i>share a truck</i>"]
    F --> G["Report<br/>the real price"]
    G -.-> B

    classDef a fill:#EDEDE1,stroke:#8A8A7A,color:#16160F
    classDef b fill:#1F3D2B,stroke:#1F3D2B,color:#FFFFFF
    classDef c fill:#16160F,stroke:#16160F,color:#FFFFFF
    class A,B,E,F a
    class C,D b
    class G c
```

**One line for the slide:** five taps from opening the app to knowing what to do.

---

## 3. WhatsApp bot

```mermaid
graph LR
    A["🙏 Namaskar<br/>which crop?"] --> B["🧅 onion<br/>80 quintal"]
    B --> C["Grade?<br/>A · B · C"]
    C --> D["Stored?<br/>shed · cold"]
    D --> E["✅ Sell 50 today<br/>hold 30 · +₹6,240"]
    E --> F["💬 What price<br/>did you get?"]

    classDef q fill:#EDEDE1,stroke:#8A8A7A,color:#16160F
    classDef u fill:#D9FDD3,stroke:#1F3D2B,color:#16160F
    classDef r fill:#1F3D2B,stroke:#1F3D2B,color:#FFFFFF
    class A,C,D q
    class B u
    class E,F r
```

**One line for the slide:** works in Marathi, on a ₹4,000 phone, with buttons —
nothing to type but a number.

---

## Optional: the one-slide version

If you only have room for a single diagram, use this — it carries the whole
argument in six boxes.

```mermaid
graph LR
    A["Mandi price<br/><b>₹2,010</b>"] --> B["− commission<br/>− cess · hamali"]
    B --> C["− transport<br/>62 km"]
    C --> D["− spoilage<br/>while waiting"]
    D --> E["<b>₹1,842</b><br/>actually in hand"]
    E --> F["🎯 So sell HERE,<br/>not there"]

    classDef x fill:#EDEDE1,stroke:#8A8A7A,color:#16160F
    classDef y fill:#B4342B,stroke:#B4342B,color:#FFFFFF
    classDef z fill:#1F3D2B,stroke:#1F3D2B,color:#FFFFFF
    class A x
    class B,C,D y
    class E,F z
```

**One line for the slide:** every other product shows the ₹2,010. We show the
₹1,842 — and that changes which mandi he drives to.
