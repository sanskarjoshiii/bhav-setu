"use client";

import { usePathname } from "next/navigation";
import { MessageCircle } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { t } from "@/lib/i18n";

const PREFILL = encodeURIComponent(
  "Hi Bhav Setu, I have 80 quintals of onion, grade B, stored in a shed. What should I do?"
);
const DEMO_NUMBER = "919673338564";

/** Deep link into WhatsApp with the message prefilled — the judge only has to hit send. */
export default function WhatsAppCTA() {
  const pathname = usePathname();
  const { language } = useAuth();
  if (pathname.startsWith("/chat") || pathname === "/login" || pathname === "/signup") return null;

  return (
    <a
      href={`https://wa.me/${DEMO_NUMBER}?text=${PREFILL}`}
      target="_blank"
      rel="noreferrer"
      className="fixed bottom-6 right-6 z-[60] inline-flex items-center gap-2.5 rounded-full bg-ink px-5 py-3.5 text-[0.88rem] font-medium text-cream shadow-pop transition hover:scale-[1.02]"
    >
      <MessageCircle size={17} />
      {t("whatsapp_cta", language)}
    </a>
  );
}
