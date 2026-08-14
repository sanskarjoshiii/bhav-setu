"use client";

import PageHeader from "@/components/PageHeader";
import Section from "@/components/Section";
import { SALE_REPORTS } from "@/lib/mock/transparency";
import { plainPct, qtl, rupees } from "@/lib/format";
import { longDate } from "@/lib/seed";

/** TODO (Phase 8): GET /api/v1/sale-reports?farmer=me */
export default function MyReportsPage() {
  const mine = SALE_REPORTS.slice(0, 6);

  return (
    <>
      <PageHeader
        eyebrow="My sale reports"
        title="What you told us you got"
        lede="Every price you report makes the next recommendation better — for you and for everyone else in your taluka."
      >
        <button className="btn-primary">Report a sale</button>
      </PageHeader>

      <Section>
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px]">
              <thead className="border-b border-line bg-panel/40">
                <tr>
                  <th className="th">Report</th>
                  <th className="th">Mandi</th>
                  <th className="th">Date</th>
                  <th className="th text-right">Quantity</th>
                  <th className="th text-right">Quoted</th>
                  <th className="th text-right">Received</th>
                  <th className="th text-right">Gap</th>
                  <th className="th">Followed advice</th>
                </tr>
              </thead>
              <tbody>
                {mine.map((r) => (
                  <tr key={r.id} className="border-b border-line/70 last:border-0">
                    <td className="td font-mono text-[0.78rem] text-muted">{r.id}</td>
                    <td className="td font-medium">{r.mandi}</td>
                    <td className="td text-muted">{longDate(r.date)}</td>
                    <td className="td text-right tabular-nums text-muted">{qtl(r.qtl)}</td>
                    <td className="td text-right tabular-nums text-muted">
                      {rupees(r.quotedPerQtl)}
                    </td>
                    <td className="td text-right font-semibold tabular-nums">
                      {rupees(r.receivedPerQtl)}
                    </td>
                    <td className="td text-right tabular-nums text-down">
                      −{plainPct(r.gapPct)}
                    </td>
                    <td className="td">
                      <span className="chip">{r.followedAdvice ? "Yes" : "No"}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </Section>
    </>
  );
}
