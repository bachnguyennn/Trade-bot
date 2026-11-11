/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: { DEFAULT: "#0f1419", raised: "#161d26", border: "#263241" },
        ink: { DEFAULT: "#e6edf3", muted: "#8b9bb0", faint: "#5d6b7e" },
        accent: "#4c9aff",
        gain: "#3fb68b",
        loss: "#e5534b",
        warn: "#d4a72c",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "Consolas", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
