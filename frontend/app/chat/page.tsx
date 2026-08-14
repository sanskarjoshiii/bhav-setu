"use client";

import { MessageCircle, Smartphone, Repeat } from "lucide-react";
import PageHeader from "@/components/PageHeader";
import Section from "@/components/Section";
import ChatWindow from "@/components/ChatWindow";

const NOTES = [
  {
    icon: Repeat,
    title: "The same engine as WhatsApp",
    body: "This simulator calls the identical bot function the WhatsApp webhook calls. If Meta approval or the tunnel fails on demo day, nothing about the story changes.",
  },
  {
    icon: Smartphone,
    title: "Built for a ₹4,000 phone",
    body: "Short messages, quick-reply buttons, no menus to memorise. It answers in Marathi or English depending on how you write to it.",
  },
  {
    icon: MessageCircle,
    title: "It asks what you actually got",
    body: "After a sale it follows up for the real price. That answer feeds the Transparency page and improves the next recommendation.",
  },
];

export default function ChatPage() {
  return (
    <>
      <PageHeader
        eyebrow="Chat"
        title="Ask it like you would ask a neighbour"
        lede="Type your crop, quantity and grade. The bot replies with the same plan the Advisor page produces — in Marathi if you prefer."
      />

      <Section>
        <div className="grid gap-10 lg:grid-cols-[1fr_430px] lg:items-start">
          <div className="space-y-3">
            {NOTES.map((n) => (
              <div key={n.title} className="card flex gap-4 p-6">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-panel">
                  <n.icon size={18} />
                </span>
                <div>
                  <h3 className="h3">{n.title}</h3>
                  <p className="mt-2 text-[0.88rem] leading-relaxed text-muted">{n.body}</p>
                </div>
              </div>
            ))}

            <div className="card p-6">
              <p className="eyebrow">The default flow</p>
              <ol className="mt-3.5 space-y-2.5">
                {[
                  ["Greeting", "It introduces itself and asks for crop and quantity"],
                  ["Crop", "“onion 80 quintal” — or tap a button"],
                  ["Grade", "A, B or C"],
                  ["Storage", "Shed, open or cold store"],
                  ["Advice", "Split plan, reason, confidence, and the rupee gain"],
                  ["Sale report", "“I sold today” → it asks the price you really got"],
                  ["Recorded", "Thanks you and files it under History"],
                ].map(([step, detail], i) => (
                  <li key={step} className="flex gap-3">
                    <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-panel text-[0.66rem] font-bold">
                      {i + 1}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[0.86rem] font-medium">{step}</span>
                      <span className="block text-[0.8rem] text-muted">{detail}</span>
                    </span>
                  </li>
                ))}
              </ol>
              <p className="mt-4 rounded-xl bg-panel/60 px-4 py-3 text-[0.8rem] text-muted">
                Type <span className="font-mono text-ink">POOL</span> at any point to see the
                shared-truck offer, and anything it does not understand gets a help message rather
                than a dead end.
              </p>
            </div>
          </div>

          <div className="lg:sticky lg:top-24">
            <ChatWindow />
          </div>
        </div>
      </Section>
    </>
  );
}
