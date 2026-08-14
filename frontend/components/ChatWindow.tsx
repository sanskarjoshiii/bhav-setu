"use client";

import { useEffect, useRef, useState } from "react";
import { Check, CheckCheck, Phone, Send, Video } from "lucide-react";
import type { ChatMessage } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { nextReply, openingMessages, resetChat } from "@/lib/mock/chat";
import { cx } from "@/lib/format";

/**
 * WhatsApp-lookalike simulator. It calls the same `nextReply` the real webhook
 * will call, so if Meta approval falls through on demo day the story is unchanged.
 */
export default function ChatWindow() {
  const { language } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [typing, setTyping] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    resetChat();
    setMessages(openingMessages(language));
  }, [language]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, typing]);

  function send(text: string) {
    const value = text.trim();
    if (!value) return;

    const stamp = new Date().toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
    setMessages((m) => [...m, { id: `u-${Date.now()}`, from: "user", text: value, time: stamp }]);
    setDraft("");
    setTyping(true);

    window.setTimeout(() => {
      const replies = nextReply(value, language);
      setTyping(false);
      setMessages((m) => [...m, ...replies]);
    }, 900);
  }

  const lastButtons = messages[messages.length - 1]?.buttons;

  return (
    <div className="mx-auto flex h-[640px] w-full max-w-[430px] flex-col overflow-hidden rounded-[26px] border border-line bg-[#EDE5DC] shadow-pop">
      <div className="flex items-center gap-3 bg-[#1F3D2B] px-4 py-3 text-white">
        <span className="grid h-9 w-9 place-items-center rounded-full bg-white/15 text-[0.8rem] font-bold">
          BS
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[0.92rem] font-semibold">Bhav Setu</p>
          <p className="text-[0.7rem] text-white/70">{typing ? "typing…" : "online"}</p>
        </div>
        <Video size={17} className="opacity-80" />
        <Phone size={16} className="opacity-80" />
      </div>

      <div
        ref={scrollRef}
        className="flex-1 space-y-2 overflow-y-auto px-3.5 py-4"
        style={{
          backgroundImage:
            "radial-gradient(circle at 20% 30%, rgba(255,255,255,0.5) 0, transparent 45%), radial-gradient(circle at 80% 70%, rgba(255,255,255,0.35) 0, transparent 40%)",
        }}
      >
        {messages.map((m) => (
          <div
            key={m.id}
            className={cx("flex", m.from === "user" ? "justify-end" : "justify-start")}
          >
            <div
              className={cx(
                "max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-[0.86rem] leading-relaxed shadow-sm",
                m.from === "user"
                  ? "rounded-br-sm bg-[#D9FDD3] text-ink"
                  : "rounded-bl-sm bg-white text-ink"
              )}
            >
              {m.text.split("*").map((part, i) =>
                i % 2 === 1 ? (
                  <strong key={i}>{part}</strong>
                ) : (
                  <span key={i}>{part}</span>
                )
              )}
              <span className="mt-1 flex items-center justify-end gap-1 text-[0.62rem] text-ink/40">
                {m.time}
                {m.from === "user" && <CheckCheck size={12} className="text-[#53BDEB]" />}
              </span>
            </div>
          </div>
        ))}

        {typing && (
          <div className="flex justify-start">
            <div className="flex gap-1 rounded-2xl rounded-bl-sm bg-white px-4 py-3 shadow-sm">
              {[0, 150, 300].map((d) => (
                <span
                  key={d}
                  className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink/30"
                  style={{ animationDelay: `${d}ms` }}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {lastButtons && !typing && (
        <div className="flex flex-wrap gap-2 border-t border-black/5 bg-[#EDE5DC] px-3 py-2.5">
          {lastButtons.map((b) => (
            <button
              key={b}
              onClick={() => send(b)}
              className="rounded-full border border-[#1F3D2B]/25 bg-white px-3.5 py-1.5 text-[0.78rem] font-medium text-[#1F3D2B] transition hover:bg-[#1F3D2B] hover:text-white"
            >
              {b}
            </button>
          ))}
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
        className="flex items-center gap-2 bg-[#EDE5DC] px-3 pb-3.5 pt-1"
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={language === "mr" ? "संदेश लिहा…" : "Type a message…"}
          className="flex-1 rounded-full bg-white px-4 py-2.5 text-[0.86rem] outline-none"
        />
        <button
          type="submit"
          className="grid h-10 w-10 place-items-center rounded-full bg-[#1F3D2B] text-white"
          aria-label="Send"
        >
          <Send size={16} />
        </button>
      </form>
    </div>
  );
}
