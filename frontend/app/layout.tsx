import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { HistoryProvider } from "@/lib/history";
import Navbar from "@/components/Navbar";
import Footer from "@/components/Footer";
import WhatsAppCTA from "@/components/WhatsAppCTA";

export const metadata: Metadata = {
  title: "Bhav Setu — selling decisions for farmers",
  description:
    "Forecasts, net-in-hand economics and a sell/hold decision for onion farmers in the Nashik belt.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans">
        <AuthProvider>
          <HistoryProvider>
          <Navbar />
          <main className="pb-24 pt-8">{children}</main>
          <Footer />
          <WhatsAppCTA />
          </HistoryProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
