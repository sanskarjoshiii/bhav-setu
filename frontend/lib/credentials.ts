import type { RiskProfile } from "./types";

/**
 * Seeded demo accounts. There is no password check anywhere — logging in with
 * any of these (or with anything at all) just picks a profile and moves on.
 *
 * They exist so a demo can show different farmers with different risk appetites
 * and villages without anyone having to sign up on camera.
 */
export interface DemoAccount {
  phone: string;
  otp: string;
  name: string;
  village: string;
  district: string;
  riskProfile: RiskProfile;
  note: string;
}

export const DEMO_ACCOUNTS: DemoAccount[] = [
  {
    phone: "9673338564",
    otp: "123456",
    name: "Sanskar Joshi",
    village: "Vinchur",
    district: "Nashik",
    riskProfile: "balanced",
    note: "Main demo account — 80 qtl onion in a shed",
  },
  {
    phone: "9545616125",
    otp: "123456",
    name: "Sunita Jadhav",
    village: "Niphad",
    district: "Nashik",
    riskProfile: "cautious",
    note: "Has a loan — gets safer, sell-sooner advice",
  },
  {
    phone: "9356476263",
    otp: "123456",
    name: "Balasaheb More",
    village: "Saykheda",
    district: "Nashik",
    riskProfile: "aggressive",
    note: "Cold store access — willing to hold longer",
  },
];

export function findAccount(phone: string): DemoAccount | undefined {
  const digits = phone.replace(/[^0-9]/g, "").slice(-10);
  return DEMO_ACCOUNTS.find((a) => a.phone === digits);
}
