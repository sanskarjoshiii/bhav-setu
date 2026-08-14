import Link from "next/link";
import { Sprout } from "lucide-react";

const COLUMNS = [
  {
    title: "Product",
    links: [
      ["Advisor", "/advisor"],
      ["Mandi Compare", "/compare"],
      ["Accuracy", "/accuracy"],
      ["Transparency", "/transparency"],
    ],
  },
  {
    title: "Farmers",
    links: [
      ["WhatsApp bot", "/chat"],
      ["My lots", "/lots"],
      ["My sale reports", "/reports"],
      ["Help", "/help"],
    ],
  },
  {
    title: "About",
    links: [
      ["How it works", "/about"],
      ["Data sources", "/about#sources"],
      ["Method", "/about#method"],
    ],
  },
];

export default function Footer() {
  return (
    <footer className="border-t border-line bg-panel/40">
      <div className="shell grid gap-10 py-14 md:grid-cols-[1.4fr_repeat(3,1fr)]">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="grid h-8 w-8 place-items-center rounded-full bg-ink text-cream">
              <Sprout size={16} />
            </span>
            <span className="text-[1.05rem] font-bold tracking-[-0.02em]">Bhav Setu</span>
          </div>
          <p className="mt-4 max-w-xs text-[0.88rem] leading-relaxed text-muted">
            A selling-decision engine for onion farmers in the Nashik belt — forecasts with a
            range, real net-in-hand economics, and one clear recommendation.
          </p>
        </div>

        {COLUMNS.map((col) => (
          <div key={col.title}>
            <p className="eyebrow">{col.title}</p>
            <ul className="mt-4 space-y-2.5">
              {col.links.map(([label, href]) => (
                <li key={label}>
                  <Link href={href} className="text-[0.88rem] text-muted transition hover:text-ink">
                    {label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="border-t border-line">
        <div className="shell flex flex-col gap-2 py-5 text-[0.78rem] text-muted sm:flex-row sm:items-center sm:justify-between">
          <p>Prices from Agmarknet / data.gov.in · Weather from Open-Meteo · Road distance from OSRM</p>
          <p>© 2026 Bhav Setu · Nashik, Maharashtra</p>
        </div>
      </div>
    </footer>
  );
}
