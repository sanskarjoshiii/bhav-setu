"use client";

/**
 * Demo-only auth. State lives in localStorage; no password is ever checked and
 * nothing leaves the browser.
 *
 * TODO (Phase 8+): replace with a real session cookie from the API. Everything
 * outside this file talks to `useAuth()`, so the swap is contained here.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { Language, SessionUser } from "./types";
import { DEMO_ACCOUNTS, findAccount } from "./credentials";

const STORAGE_KEY = "bhavsetu.session";

interface AuthState {
  user: SessionUser | null;
  ready: boolean;
  language: Language;
  setLanguage: (l: Language) => void;
  login: (phone: string) => SessionUser;
  signup: (data: Partial<SessionUser> & { name: string; phone: string }) => SessionUser;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

const DEMO_USER: SessionUser = {
  name: "Sanskar Joshi",
  phone: "+91 96733 38564",
  village: "Vinchur",
  language: "en",
  riskProfile: "balanced",
};

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [language, setLanguageState] = useState<Language>("en");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as SessionUser;
        setUser(parsed);
        setLanguageState(parsed.language ?? "en");
      }
    } catch {
      // a corrupt demo session is not worth crashing over
    }
    setReady(true);
  }, []);

  const persist = useCallback((next: SessionUser | null) => {
    setUser(next);
    if (next) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    else window.localStorage.removeItem(STORAGE_KEY);
  }, []);

  /** Looks the number up in the seeded accounts so different demo logins get
   *  different names, villages and risk profiles. Unknown numbers still work. */
  const login = useCallback(
    (phone: string) => {
      const account = findAccount(phone) ?? DEMO_ACCOUNTS[0];
      const next: SessionUser = {
        name: account.name,
        phone: `+91 ${account.phone}`,
        village: account.village,
        language,
        riskProfile: account.riskProfile,
      };
      persist(next);
      return next;
    },
    [language, persist]
  );

  const signup = useCallback(
    (data: Partial<SessionUser> & { name: string; phone: string }) => {
      const next: SessionUser = {
        name: data.name,
        phone: data.phone,
        village: data.village ?? "Vinchur",
        language: data.language ?? language,
        riskProfile: data.riskProfile ?? "balanced",
      };
      persist(next);
      return next;
    },
    [language, persist]
  );

  const logout = useCallback(() => persist(null), [persist]);

  const setLanguage = useCallback(
    (l: Language) => {
      setLanguageState(l);
      setUser((current) => {
        if (!current) return current;
        const next = { ...current, language: l };
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
        return next;
      });
    },
    []
  );

  const value = useMemo(
    () => ({ user, ready, language, setLanguage, login, signup, logout }),
    [user, ready, language, setLanguage, login, signup, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
