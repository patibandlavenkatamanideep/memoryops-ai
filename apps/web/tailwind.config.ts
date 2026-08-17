import type { Config } from "tailwindcss";

/**
 * Tailwind is the delivery mechanism for the tokens in app/globals.css, not a second
 * palette. Nothing here is a literal colour: every entry resolves a CSS variable, so
 * the token file stays the single place a colour is decided.
 *
 * `<alpha-value>` is what makes `bg-accent/10` work against a variable-backed colour;
 * it requires the variables to hold space-separated RGB channels.
 */
const withAlpha = (token: string) => `rgb(var(${token}) / <alpha-value>)`;

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: withAlpha("--mo-canvas"),
        surface: {
          DEFAULT: withAlpha("--mo-surface"),
          raised: withAlpha("--mo-surface-raised"),
          hover: withAlpha("--mo-surface-hover"),
          sunken: withAlpha("--mo-surface-sunken"),
        },
        line: {
          DEFAULT: withAlpha("--mo-border"),
          strong: withAlpha("--mo-border-strong"),
        },
        fg: {
          DEFAULT: withAlpha("--mo-fg"),
          secondary: withAlpha("--mo-fg-secondary"),
          muted: withAlpha("--mo-fg-muted"),
        },
        accent: {
          DEFAULT: withAlpha("--mo-accent"),
          strong: withAlpha("--mo-accent-strong"),
        },
        ok: withAlpha("--mo-ok"),
        warn: withAlpha("--mo-warn"),
        danger: withAlpha("--mo-danger"),
        info: withAlpha("--mo-info"),
        neutral: withAlpha("--mo-neutral"),
        focus: withAlpha("--mo-focus"),

        // Pre-existing aliases. Kept so a surface that has not been migrated to the
        // ui/ primitives still resolves to the token set rather than breaking.
        ink: withAlpha("--mo-canvas"),
        panel: withAlpha("--mo-surface"),
      },
      fontFamily: {
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "SF Mono",
          "Menlo",
          "Consolas",
          "Liberation Mono",
          "monospace",
        ],
      },
      fontSize: {
        // Section eyebrows and table headers. Small, spaced, uppercase — used often
        // enough that redefining it per component was drifting.
        label: ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.06em" }],
      },
      borderRadius: {
        panel: "0.75rem",
      },
      boxShadow: {
        // Depth comes from borders and surface tiers; shadow is reserved for things
        // that genuinely float above the page.
        overlay: "0 24px 60px -12px rgb(0 0 0 / 0.7)",
      },
      keyframes: {
        "mo-pulse": {
          "0%, 100%": { opacity: "0.45" },
          "50%": { opacity: "0.85" },
        },
      },
      animation: {
        "mo-pulse": "mo-pulse 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
