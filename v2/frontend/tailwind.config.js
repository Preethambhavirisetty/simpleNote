/** @type {import('tailwindcss').Config} */
const palette = (name) => `rgb(var(--palette-${name}) / <alpha-value>)`

export default {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        white: palette('white'),
        black: palette('black'),
        zinc: {
          50: palette('zinc-50'), 100: palette('zinc-100'), 200: palette('zinc-200'),
          300: palette('zinc-300'), 400: palette('zinc-400'), 500: palette('zinc-500'),
          600: palette('zinc-600'), 700: palette('zinc-700'), 800: palette('zinc-800'),
          900: palette('zinc-900'), 950: palette('zinc-950'),
        },
        indigo: {
          300: palette('indigo-300'), 400: palette('indigo-400'), 500: palette('indigo-500'),
          600: palette('indigo-600'), 900: palette('indigo-900'),
        },
        red: {
          50: palette('red-50'), 300: palette('red-300'), 400: palette('red-400'),
          500: palette('red-500'), 900: palette('red-900'), 950: palette('red-950'),
        },
        emerald: { 500: palette('emerald-500') },
      },
      fontFamily: { sans: 'var(--font-sans)', mono: 'var(--font-mono)' },
      fontSize: {
        caption: 'var(--text-caption)', label: 'var(--text-label)', xs: 'var(--text-xs)',
        sm: 'var(--text-sm)', base: 'var(--text-base)', lg: 'var(--text-lg)',
        xl: 'var(--text-xl)', '2xl': 'var(--text-2xl)',
      },
      borderRadius: {
        sm: 'var(--radius-xs)', DEFAULT: 'var(--radius-sm)', md: 'var(--radius-md)',
        lg: 'var(--radius-lg)', xl: 'var(--radius-xl)', '2xl': 'var(--radius-xl)', full: 'var(--radius-full)',
      },
    },
  },
  plugins: [],
}
