import type { Config } from "tailwindcss";

/**
 * The whole visual language lives here. Cream page, white cards, near-black ink,
 * one muted tone for secondary text and a single hairline border colour.
 * Nothing else — the design reads as "minimal" because the palette is tiny.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        cream: "#F3F3EA",
        panel: "#EDEDE1",
        ink: "#16160F",
        muted: "#6F6F63",
        line: "#E2E2D6",
        card: "#FFFFFF",
        accent: "#1F3D2B",
        up: "#177245",
        down: "#B4342B",
        band: "#8AA79A",
      },
      // No webfont: the build must not depend on the network, and Segoe UI /
      // -apple-system are close enough to the reference design.
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      borderRadius: {
        xl: "0.875rem",
        "2xl": "1.125rem",
      },
      boxShadow: {
        card: "0 1px 2px rgba(22,22,15,0.04)",
        pop: "0 8px 30px rgba(22,22,15,0.12)",
      },
      maxWidth: {
        shell: "1180px",
      },
    },
  },
  plugins: [],
};
export default config;
