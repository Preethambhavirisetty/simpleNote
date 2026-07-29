/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      fontFamily: { sans: 'var(--font-sans)', mono: 'var(--font-mono)' },
      fontSize: {
        caption: 'var(--text-caption)', xs: 'var(--text-xs)',
        sm: 'var(--text-sm)', base: 'var(--text-base)', lg: 'var(--text-lg)',
        xl: 'var(--text-xl)', '2xl': 'var(--text-2xl)', '3xl': 'var(--text-3xl)',
        '4xl': 'var(--text-4xl)', '5xl': 'var(--text-5xl)', '6xl': 'var(--text-6xl)',
      },
    },
  },
  plugins: [],
}
