/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // FINTRACK-51: first real brand palette for FinTrack -- no
        // existing brand assets, so this is a from-scratch decision
        // (see Fintrack/audit/FINTRACK-51-*.json for the design-approach
        // rationale: code-first Tailwind tokens, no Figma). Indigo reads
        // as trustworthy/financial without being a literal bank-blue
        // cliché; kept to a single accent scale plus Tailwind's stock
        // slate/emerald/amber/rose for semantic states so there's exactly
        // one new thing to maintain, not a whole custom palette.
        brand: {
          50: "#eef2ff",
          100: "#e0e7ff",
          200: "#c7d2fe",
          300: "#a5b4fc",
          400: "#818cf8",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
          800: "#3730a3",
          900: "#312e81",
        },
      },
      fontFamily: {
        // "Inter" first with the full system-font fallback stack behind
        // it -- no webfont is loaded (index.html's CSP has no font-src
        // exception and we didn't want to widen it for a font), so this
        // silently falls through to the system stack on every machine.
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};
