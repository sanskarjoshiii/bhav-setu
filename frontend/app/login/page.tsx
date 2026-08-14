"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Loader2, MessageCircle, ShieldCheck, Sprout } from "lucide-react";
import { useAuth } from "@/lib/auth";

const REASSURANCE = [
  { icon: ShieldCheck, text: "We never share your number with any trader, agent or buyer." },
  { icon: MessageCircle, text: "The code arrives on WhatsApp — no SMS charges." },
];

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [stage, setStage] = useState<"phone" | "otp">("phone");
  const [busy, setBusy] = useState(false);

  function requestOtp(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setTimeout(() => {
      setBusy(false);
      setStage("otp");
    }, 700);
  }

  function verify(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setTimeout(() => {
      login(phone);
      router.push("/dashboard");
    }, 700);
  }

  return (
    <div className="shell grid min-h-[72vh] items-center gap-12 py-10 lg:grid-cols-2">
      <div className="hidden lg:block">
        <span className="grid h-11 w-11 place-items-center rounded-full bg-ink text-cream">
          <Sprout size={20} />
        </span>
        <h1 className="h2 mt-6 max-w-md">Your lots, your history, your advice.</h1>
        <p className="lede mt-4 max-w-md">
          Log in to keep track of what you have in store, what we recommended, and every question you
          have asked us.
        </p>

        <ul className="mt-8 max-w-md space-y-3">
          {REASSURANCE.map((r) => (
            <li key={r.text} className="flex items-start gap-3">
              <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-panel">
                <r.icon size={15} />
              </span>
              <p className="text-[0.88rem] leading-relaxed text-muted">{r.text}</p>
            </li>
          ))}
        </ul>
      </div>

      <div className="mx-auto w-full max-w-[420px]">
        <div className="card p-8">
          <h2 className="h3">{stage === "phone" ? "Log in" : "Enter the code"}</h2>
          <p className="mt-1.5 text-[0.88rem] text-muted">
            {stage === "phone"
              ? "We send a one-time code to your WhatsApp number."
              : `Sent to +91 ${phone}. It expires in 10 minutes.`}
          </p>

          {stage === "phone" ? (
            <form onSubmit={requestOtp} className="mt-7 space-y-5">
              <div>
                <label className="label" htmlFor="phone">
                  Mobile number
                </label>
                <div className="flex items-center gap-2">
                  <span className="rounded-xl border border-line bg-panel/50 px-3.5 py-3 text-[0.95rem] text-muted">
                    +91
                  </span>
                  <input
                    id="phone"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value.replace(/[^0-9]/g, ""))}
                    className="input flex-1"
                    placeholder="00000 00000"
                    inputMode="tel"
                    maxLength={10}
                    autoComplete="tel"
                  />
                </div>
              </div>
              <button disabled={busy || phone.length < 10} className="btn-primary w-full">
                {busy && <Loader2 size={15} className="animate-spin" />}
                Send code
              </button>
            </form>
          ) : (
            <form onSubmit={verify} className="mt-7 space-y-5">
              <div>
                <label className="label" htmlFor="otp">
                  Six-digit code
                </label>
                <input
                  id="otp"
                  value={otp}
                  onChange={(e) => setOtp(e.target.value.replace(/[^0-9]/g, ""))}
                  placeholder="------"
                  className="input text-center text-[1.4rem] tracking-[0.5em]"
                  inputMode="numeric"
                  maxLength={6}
                  autoComplete="one-time-code"
                />
              </div>
              <button disabled={busy || otp.length < 6} className="btn-primary w-full">
                {busy && <Loader2 size={15} className="animate-spin" />}
                Log in
                <ArrowRight size={15} />
              </button>
              <button type="button" onClick={() => setStage("phone")} className="btn-quiet w-full">
                Use a different number
              </button>
            </form>
          )}

          <p className="mt-7 border-t border-line pt-5 text-center text-[0.85rem] text-muted">
            New here?{" "}
            <Link href="/signup" className="font-medium text-ink underline underline-offset-4">
              Create an account
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
