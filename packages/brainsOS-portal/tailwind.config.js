/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        "obsidian": "#07090E",
        "surface-deck": "#0B0E14",
        "surface-card": "#111622",
        "surface-container": "#151a26",
        "surface-high": "#1e2535",
        "primary-cyan": "#00f2fe",
        "accent-pink": "#ec4899",
        "accent-amber": "#f59e0b",
        "accent-emerald": "#10b981",
        "accent-blue": "#3b82f6",
        "accent-yellow": "#eab308",
        "matrix-white": "#f8fafc",
        "slate-matrix": "#94a3b8",
        "muted-phosphor": "#475569"
      },
      fontFamily: {
        headline: ["'Space Grotesk'", "sans-serif"],
        body: ["'Geist'", "-apple-system", "sans-serif"],
        mono: ["'JetBrains Mono'", "monospace"]
      }
    },
  },
  plugins: [],
};
