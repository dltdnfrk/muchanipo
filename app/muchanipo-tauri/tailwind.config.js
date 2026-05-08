/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "var(--border)",
        input: "var(--border)",
        ring: "hsl(var(--ring))",
        background: "var(--bg)",
        foreground: "var(--text)",
        primary: {
          DEFAULT: "var(--accent-ink)",
          foreground: "var(--inverse-text)",
        },
        secondary: {
          DEFAULT: "var(--surface-muted)",
          foreground: "var(--text-secondary)",
        },
        muted: {
          DEFAULT: "var(--surface-muted)",
          foreground: "var(--text-tertiary)",
        },
        accent: {
          DEFAULT: "var(--surface-muted)",
          foreground: "var(--text)",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        card: {
          DEFAULT: "var(--surface)",
          foreground: "var(--text)",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [],
};
