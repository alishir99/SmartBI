/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // Every colour is a CSS custom property so light/dark swap in one place
      // (see src/index.css). Do not use opacity modifiers on these.
      colors: {
        page: 'var(--page)',
        surface: 'var(--surface)',
        'surface-2': 'var(--surface-2)',
        'surface-3': 'var(--surface-3)',
        ink: 'var(--text)',
        'ink-secondary': 'var(--text-secondary)',
        'ink-muted': 'var(--text-muted)',
        hairline: 'var(--hairline)',
        'hairline-strong': 'var(--hairline-strong)',
        accent: 'var(--accent)',
        'accent-hover': 'var(--accent-hover)',
        'accent-fg': 'var(--accent-fg)',
        'accent-soft': 'var(--accent-soft)',
        pos: 'var(--pos)',
        neg: 'var(--neg)',
        'notice-bg': 'var(--notice-bg)',
        'notice-border': 'var(--notice-border)',
        'notice-ink': 'var(--notice-ink)',
      },
      fontFamily: {
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          '"SF Pro Display"',
          '"SF Pro Text"',
          'Inter',
          '"Helvetica Neue"',
          'Arial',
          'sans-serif',
        ],
        mono: ['ui-monospace', 'SFMono-Regular', '"SF Mono"', 'Menlo', 'Consolas', 'monospace'],
      },
      fontSize: {
        // Type scale, Apple-ish: 11 12 13 15 17 21 28 40 56
        '2xs': ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.005em' }],
        xs: ['0.75rem', { lineHeight: '1.0625rem' }],
        sm: ['0.8125rem', { lineHeight: '1.125rem' }],
        base: ['0.9375rem', { lineHeight: '1.5rem' }],
        lg: ['1.0625rem', { lineHeight: '1.4rem', letterSpacing: '-0.01em' }],
        xl: ['1.3125rem', { lineHeight: '1.6rem', letterSpacing: '-0.014em' }],
        '2xl': ['1.75rem', { lineHeight: '2.0625rem', letterSpacing: '-0.02em' }],
        '3xl': ['2.5rem', { lineHeight: '2.75rem', letterSpacing: '-0.025em' }],
        '4xl': ['3.5rem', { lineHeight: '3.75rem', letterSpacing: '-0.03em' }],
      },
      borderRadius: {
        card: '18px',
        tile: '14px',
        pill: '980px',
      },
      boxShadow: {
        card: 'var(--shadow-card)',
        lift: 'var(--shadow-lift)',
        pop: 'var(--shadow-pop)',
      },
      transitionTimingFunction: {
        out: 'cubic-bezier(0.25, 0.1, 0.25, 1)',
      },
      keyframes: {
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': { from: { opacity: '0' }, to: { opacity: '1' } },
        shimmer: { from: { backgroundPosition: '200% 0' }, to: { backgroundPosition: '-200% 0' } },
      },
      animation: {
        'fade-up': 'fade-up 320ms cubic-bezier(0.25, 0.1, 0.25, 1) both',
        'fade-in': 'fade-in 200ms ease-out both',
        shimmer: 'shimmer 1.6s linear infinite',
      },
    },
  },
  plugins: [],
}
