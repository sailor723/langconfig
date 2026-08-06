/** @type {import('tailwindcss').Config} */

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    container: {
      center: true,
    },
    extend: {
      colors: {
        // "Signal Console" graphite neutrals
        ink: {
          950: "#0b0d10",
          900: "#0d0f12",
          850: "#111419",
          800: "#15181d",
          700: "#1c2027",
          600: "#232830",
          500: "#2e3540",
          400: "#4a5361",
          300: "#6b7686",
          200: "#9aa3b0",
          100: "#c6ccd6",
          50: "#e9ecf1",
        },
        // warm amber accent for execution / active state
        signal: {
          DEFAULT: "#e8a33d",
          300: "#f0c073",
          400: "#ecb158",
          500: "#e8a33d",
          600: "#d18a24",
          700: "#a96f1c",
        },
        // teal secondary for online / success states
        pulse: {
          DEFAULT: "#2dd4bf",
          400: "#5eead4",
          600: "#14b8a6",
        },
      },
      fontFamily: {
        sans: ["Archivo", "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(232, 163, 61, 0.35), 0 0 18px rgba(232, 163, 61, 0.18)",
        "glow-teal": "0 0 0 1px rgba(45, 212, 191, 0.35), 0 0 18px rgba(45, 212, 191, 0.18)",
        panel: "0 1px 0 rgba(255,255,255,0.03) inset, 0 8px 24px rgba(0,0,0,0.35)",
      },
    },
  },
  plugins: [],
};
