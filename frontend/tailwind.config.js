/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: 'rgb(var(--bg) / <alpha-value>)',
        surface: 'rgb(var(--surface) / <alpha-value>)',
        'surface-2': 'rgb(var(--surface-2) / <alpha-value>)',
        border: 'rgb(var(--border) / <alpha-value>)',
        fg: 'rgb(var(--fg) / <alpha-value>)',
        muted: 'rgb(var(--muted) / <alpha-value>)',
        brand: {
          DEFAULT: 'rgb(var(--brand) / <alpha-value>)',
          fg: 'rgb(var(--brand-fg) / <alpha-value>)',
        },
        status: {
          uploaded: 'rgb(var(--st-uploaded) / <alpha-value>)',
          transcribing: 'rgb(var(--st-transcribing) / <alpha-value>)',
          transcribed: 'rgb(var(--st-transcribed) / <alpha-value>)',
          failed: 'rgb(var(--st-failed) / <alpha-value>)',
        },
        spk: {
          0: '#38bdf8',
          1: '#a78bfa',
          2: '#34d399',
          3: '#fbbf24',
          4: '#fb7185',
          5: '#22d3ee',
          6: '#f472b6',
          7: '#818cf8',
        },
      },
      borderRadius: { card: '14px', pill: '9999px' },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgb(0 0 0 / .06), 0 8px 24px -12px rgb(0 0 0 / .25)',
      },
      keyframes: {
        pulseDot: { '0%,100%': { opacity: '1' }, '50%': { opacity: '.35' } },
        shimmer: { '100%': { transform: 'translateX(100%)' } },
      },
      animation: {
        pulseDot: 'pulseDot 1.4s ease-in-out infinite',
        shimmer: 'shimmer 1.6s infinite',
      },
    },
  },
  plugins: [],
};
