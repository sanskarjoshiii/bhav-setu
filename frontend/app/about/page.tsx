import PageHeader from "@/components/PageHeader";
import Section from "@/components/Section";

const STEPS: [string, string][] = [
  [
    "Collect",
    "Three years of daily prices and arrivals for every mandi we cover, plus weather and policy events. Cleaned, with every imputed value flagged.",
  ],
  [
    "Forecast",
    "A LightGBM quantile model predicts P10, P50 and P90 at 1, 3, 7 and 15 days. One global model — the mandi is a feature, not a separate model.",
  ],
  [
    "Cost it",
    "Commission, cess, hamali, weighing, packing, transport by road distance, storage and interest, and spoilage for every day held.",
  ],
  [
    "Decide",
    "375 plans are scored on expected net minus a penalty for the bad case, then six hard rules override the maths where they must.",
  ],
];

const SOURCES: [string, string, string][] = [
  ["Agmarknet / data.gov.in", "Daily modal price and arrivals per mandi", "Open Government Licence"],
  ["CEDA, Ashoka University", "Historical price and arrival series", "Public portal"],
  ["Open-Meteo", "Rainfall and temperature, history and forecast", "Free, no key"],
  ["OSRM", "Road distance between village and mandi", "Public demo server, cached"],
  ["Hand-curated", "Onion policy events — export bans, MEP orders, stock limits", "With source URLs"],
];

const CAVEATS = [
  "We cannot predict a policy announcement. When the government bans exports our forecast is wrong that day like everyone else, and we only model how prices decay afterwards.",
  "The cost model uses typical Nashik rates. Your own commission agent may charge differently; tell us and we will use your actual rates.",
  "District-level prices average across the markets inside a district, so a single trader's rate on a given morning can differ from what we show.",
  "Below about sixty real observations for a mandi we refuse to answer rather than guess.",
];

export default function AboutPage() {
  return (
    <>
      <PageHeader
        eyebrow="About"
        title="How it works, and what we are unsure about"
        lede="A forecast is only useful if you know how it was made and where it breaks."
      />

      <Section title="The pipeline">
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          {STEPS.map(([title, body], i) => (
            <div key={title} className="card p-6">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-ink text-[0.75rem] font-bold text-cream">
                {i + 1}
              </span>
              <h3 className="h3 mt-4">{title}</h3>
              <p className="mt-2 text-[0.86rem] leading-relaxed text-muted">{body}</p>
            </div>
          ))}
        </div>
      </Section>

      <Section id="sources" title="Data sources" description="Every number traces back to one of these.">
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[600px]">
              <thead className="border-b border-line bg-panel/40">
                <tr>
                  <th className="th">Source</th>
                  <th className="th">What we take</th>
                  <th className="th">Terms</th>
                </tr>
              </thead>
              <tbody>
                {SOURCES.map(([a, b, c]) => (
                  <tr key={a} className="border-b border-line/70 last:border-0">
                    <td className="td font-medium">{a}</td>
                    <td className="td text-muted">{b}</td>
                    <td className="td text-muted">{c}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </Section>

      <Section title="What we are not claiming">
        <div className="card space-y-4 p-7">
          {CAVEATS.map((t) => (
            <p key={t} className="border-l-2 border-line pl-4 text-[0.9rem] leading-relaxed text-muted">
              {t}
            </p>
          ))}
        </div>
      </Section>
    </>
  );
}
