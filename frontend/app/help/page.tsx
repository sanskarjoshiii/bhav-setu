import PageHeader from "@/components/PageHeader";
import Section from "@/components/Section";

const FAQ: [string, string][] = [
  [
    "What does net in hand mean?",
    "The money that actually reaches you, after commission, market cess, hamali, weighing, packing, transport and anything that spoils while you wait. The board price is never what you take home.",
  ],
  [
    "Why do you show a range instead of one price?",
    "Because nobody can predict onion to the rupee. The range is the honest answer: about eight times out of ten the real price lands inside it.",
  ],
  [
    "Why does it sometimes tell me to sell everything today?",
    "Six hard rules can override the maths — a fresh policy shock, a lot too small to justify a long trip, a hold long enough to risk spoilage, or a forecast too uncertain to bet on.",
  ],
  [
    "What happens to the price I report?",
    "It scores the mandi on the Transparency page and improves future advice. Your name is never shown next to your phone number.",
  ],
  [
    "Is my number shared with traders?",
    "No. Nothing you send is passed to any buyer, agent or trader.",
  ],
];

export default function HelpPage() {
  return (
    <>
      <PageHeader
        eyebrow="Help"
        title="Questions farmers actually ask"
        lede="If something here is unclear, ask the bot on WhatsApp in Marathi."
      />
      <Section>
        <div className="mx-auto max-w-3xl space-y-3">
          {FAQ.map(([q, a]) => (
            <details key={q} className="card p-6">
              <summary className="cursor-pointer list-none text-[1rem] font-semibold">{q}</summary>
              <p className="mt-3 text-[0.9rem] leading-relaxed text-muted">{a}</p>
            </details>
          ))}
        </div>
      </Section>
    </>
  );
}
