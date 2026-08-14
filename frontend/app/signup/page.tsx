"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Check, Loader2, Sprout } from "lucide-react";
import { useAuth } from "@/lib/auth";
import type { Language, RiskProfile } from "@/lib/types";
import { cx } from "@/lib/format";

const VILLAGES = ["Vinchur", "Niphad", "Ugaon", "Saykheda", "Kotamgaon", "Palkhed", "Dixi"];

const RISKS: { value: RiskProfile; label: string; hint: string }[] = [
  { value: "cautious", label: "Cautious", hint: "I have a loan to service" },
  { value: "balanced", label: "Balanced", hint: "Some risk is fine" },
  { value: "aggressive", label: "Aggressive", hint: "I can wait for a better price" },
];

export default function SignupPage() {
  const router = useRouter();
  const { signup, setLanguage } = useAuth();
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);

  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [village, setVillage] = useState("Vinchur");
  const [language, setLang] = useState<Language>("mr");
  const [risk, setRisk] = useState<RiskProfile>("balanced");

  function finish() {
    setBusy(true);
    setLanguage(language);
    setTimeout(() => {
      signup({ name: name || "Sanskar Joshi", phone: phone || "+91 96733 38564", village, language, riskProfile: risk });
      router.push("/advisor");
    }, 800);
  }

  return (
    <div className="shell grid min-h-[70vh] items-center gap-12 py-10 lg:grid-cols-2">
      <div className="hidden lg:block">
        <span className="grid h-11 w-11 place-items-center rounded-full bg-ink text-cream">
          <Sprout size={20} />
        </span>
        <h1 className="h2 mt-6 max-w-md">Three questions, then advice.</h1>
        <p className="lede mt-4 max-w-md">
          We only ask what changes the recommendation: where you are, what language you read, and
          how much risk you can carry.
        </p>

        <ol className="mt-8 max-w-md space-y-3">
          {["Who you are", "Where you farm", "How much risk you can take"].map((label, i) => (
            <li key={label} className="flex items-center gap-3">
              <span
                className={cx(
                  "grid h-7 w-7 place-items-center rounded-full text-[0.72rem] font-bold",
                  step > i + 1 ? "bg-accent text-cream" : step === i + 1 ? "bg-ink text-cream" : "bg-panel text-muted"
                )}
              >
                {step > i + 1 ? <Check size={13} /> : i + 1}
              </span>
              <span className={cx("text-[0.92rem]", step === i + 1 ? "font-medium" : "text-muted")}>
                {label}
              </span>
            </li>
          ))}
        </ol>
      </div>

      <div className="mx-auto w-full max-w-[420px]">
        <div className="card p-8">
          <p className="eyebrow">Step {step} of 3</p>

          {step === 1 && (
            <div className="mt-3">
              <h2 className="h3">Create your account</h2>
              <div className="mt-6 space-y-5">
                <div>
                  <label className="label" htmlFor="name">Your name</label>
                  <input id="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Sanskar Joshi" className="input" />
                </div>
                <div>
                  <label className="label" htmlFor="ph">WhatsApp number</label>
                  <input id="ph" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+91 96733 38564" className="input" inputMode="tel" />
                </div>
                <div>
                  <p className="label">Language</p>
                  <div className="flex gap-2">
                    {(["mr", "en"] as Language[]).map((l) => (
                      <button
                        key={l}
                        type="button"
                        onClick={() => setLang(l)}
                        className={cx("segment", language === l && "segment-active")}
                      >
                        {l === "mr" ? "मराठी" : "English"}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <button onClick={() => setStep(2)} className="btn-primary mt-7 w-full">
                Continue
                <ArrowRight size={15} />
              </button>
            </div>
          )}

          {step === 2 && (
            <div className="mt-3">
              <h2 className="h3">Where do you farm?</h2>
              <p className="mt-1.5 text-[0.88rem] text-muted">
                This sets the distance to each mandi, which changes your net price.
              </p>
              <div className="mt-6">
                <p className="label">Village</p>
                <div className="grid grid-cols-2 gap-2">
                  {VILLAGES.map((v) => (
                    <button
                      key={v}
                      type="button"
                      onClick={() => setVillage(v)}
                      className={cx("segment", village === v && "segment-active")}
                    >
                      {v}
                    </button>
                  ))}
                </div>
              </div>
              <div className="mt-7 flex gap-2">
                <button onClick={() => setStep(1)} className="btn-ghost flex-1">Back</button>
                <button onClick={() => setStep(3)} className="btn-primary flex-1">
                  Continue
                  <ArrowRight size={15} />
                </button>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="mt-3">
              <h2 className="h3">How much risk can you take?</h2>
              <p className="mt-1.5 text-[0.88rem] text-muted">
                A cautious farmer gets plans with a safer worst case, not just a higher average.
              </p>
              <div className="mt-6 grid gap-2">
                {RISKS.map((r) => (
                  <button
                    key={r.value}
                    type="button"
                    onClick={() => setRisk(r.value)}
                    className={cx(
                      "flex items-center justify-between rounded-xl border px-4 py-3.5 text-left transition",
                      risk === r.value ? "border-ink bg-ink text-cream" : "border-line bg-card hover:border-ink/30"
                    )}
                  >
                    <span className="text-[0.92rem] font-medium">{r.label}</span>
                    <span className={cx("text-[0.74rem]", risk === r.value ? "text-cream/70" : "text-muted")}>
                      {r.hint}
                    </span>
                  </button>
                ))}
              </div>
              <div className="mt-7 flex gap-2">
                <button onClick={() => setStep(2)} className="btn-ghost flex-1">Back</button>
                <button onClick={finish} disabled={busy} className="btn-primary flex-1">
                  {busy && <Loader2 size={15} className="animate-spin" />}
                  Finish
                </button>
              </div>
            </div>
          )}

          <p className="mt-7 border-t border-line pt-5 text-center text-[0.85rem] text-muted">
            Already have an account?{" "}
            <Link href="/login" className="font-medium text-ink underline underline-offset-4">
              Log in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
