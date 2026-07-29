import { Link } from 'react-router-dom'
import noteliteIcon from '@/assets/notelite_icon.png'

const pillars = ['Notes', 'Chat', 'Search']

const tickerItems = ['Smart Notes', 'AI Conversations', 'Instant Recall', 'Tags & Folders', 'Grounded Answers']

const sections = [
  {
    pill: 'Notes',
    icon: '✦',
    color: '#9ed858',
    title: 'Write without friction, organize without thinking.',
    copy: 'A calm, flexible editor for quick thoughts, long-form notes, and everything between — with folders and tags that stay out of your way.',
    note: 'Built for distraction-free writing',
    side: 'right',
  },
  {
    pill: 'Chat',
    icon: '⌁',
    color: '#7fb6ff',
    title: 'Ask your notes anything, get answers grounded in your own words.',
    copy: 'Turn your personal knowledge into clear answers with conversations grounded in what you have actually written — no guessing, no generic replies.',
    note: 'Conversational recall of your own notes',
    side: 'left',
  },
  {
    pill: 'Search',
    icon: '◎',
    color: '#e8b86d',
    title: 'Keep ideas connected, however you left them.',
    copy: 'Folders, tags, and intelligent retrieval keep the right context close when you need it — even months after you wrote it.',
    note: 'Find any idea in seconds',
    side: 'right',
  },
]

const techBadges = ['React', 'FastAPI', 'PostgreSQL', 'Redis', 'Qdrant', 'Vite']

export default function HomePage() {
  return (
    <div className="landing-page min-h-screen overflow-hidden text-[#20251e]">
      <div className="landing-glow landing-glow-one" />
      <div className="landing-glow landing-glow-two" />

      <header className="relative z-10 mx-auto flex max-w-7xl items-center justify-between px-6 py-6 lg:px-10">
        <Link to="/" className="flex items-center gap-2.5">
          <img src={noteliteIcon} alt="" className="h-10 w-10 rounded-xl" />
          <span className="text-lg font-semibold tracking-tight text-[#20251e]">NoteLite</span>
        </Link>

        <nav className="hidden items-center gap-8 text-sm text-[#687064] md:flex">
          <a href="#features" className="hover:text-[#20251e]">Features</a>
          <a href="#workflow" className="hover:text-[#20251e]">How it works</a>
          <a href="#stack" className="hover:text-[#20251e]">Stack</a>
        </nav>

        <Link to="/register" className="flex items-center gap-2 rounded-full border border-[#86bd45] bg-[#9ed858] px-4 py-2 text-sm font-semibold text-[#17220e] shadow-sm hover:border-[#74aa35] hover:bg-[#ace567] hover:shadow-md">
          Get started
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-white/70 text-caption text-[#17220e]">»</span>
        </Link>
      </header>

      <main className="relative z-10">
        {/* Hero */}
        <section className="mx-auto max-w-5xl px-6 pb-10 pt-10 text-center lg:px-10 lg:pt-16">
          <h1 className="text-4xl font-semibold leading-[1.05] tracking-[-0.045em] text-[#20251e] sm:text-5xl lg:text-6xl">
            Note-taking that takes you
            <br />
            from scattered to certain.
          </h1>
          <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
            {pillars.map((p) => (
              <span key={p} className="rounded-full border border-[#dfe4da] bg-white px-4 py-1.5 text-sm text-[#4f594a] shadow-sm">
                {p}
              </span>
            ))}
          </div>
        </section>

        {/* Ticker */}
        <section className="w-full">
          <div className="landing-ticker">
            <div className="landing-ticker-track">
              {[...tickerItems, ...tickerItems].map((item, i) => (
                <span key={i} className="landing-ticker-item">
                  <i>✕</i> {item}
                </span>
              ))}
            </div>
          </div>
        </section>

        {/* Dark banner */}
        <section className="mx-auto max-w-6xl px-6 pb-20 pt-8 lg:px-10">
          <div className="landing-banner px-8 py-16 text-center sm:px-16 sm:py-24">
            <div className="landing-banner-grid" />
            <div className="relative z-10 mx-auto max-w-2xl">
              <span className="mb-6 inline-flex items-center rounded-full border border-[#cfe4b5] bg-white px-3 py-1.5 text-xs font-medium text-[#4d6b2c]">
                Intelligent Retrieval
              </span>
              <h2 className="text-3xl font-semibold leading-tight text-[#20251e] sm:text-4xl">
                Never lose a thought to a blank page.
              </h2>
              <p className="mt-4 text-sm leading-6 text-[#687064] sm:text-base">
                Write freely — NoteLite remembers, connects, and surfaces what matters, automatically.
              </p>
              <Link to="/register" className="mt-8 inline-flex items-center gap-2 rounded-full bg-[#9ed858] px-6 py-3 text-sm font-semibold text-[#17220e] hover:bg-[#ace567]">
                Start writing free
              </Link>
            </div>
          </div>
        </section>

        {/* Alternating feature sections */}
        <section id="features" className="mx-auto max-w-6xl space-y-20 px-6 pb-24 lg:px-10">
          {sections.map((s) => (
            <article
              key={s.pill}
              className={`grid items-center gap-10 lg:grid-cols-2 ${s.side === 'left' ? 'lg:[&>*:first-child]:order-2' : ''}`}
            >
              <div className="landing-dotblob" style={{ color: s.color }}>
                <div className="landing-dotblob-shape" />
              </div>
              <div>
                <div className="mb-4 flex items-center gap-2">
                  <span className="rounded-full border border-[#dfe4da] bg-white px-3 py-1 text-xs font-medium text-[#4f594a]">
                    {s.pill}
                  </span>
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[#eef4e8] text-sm text-[#567832]">
                    {s.icon}
                  </span>
                </div>
                <h3 className="text-2xl font-medium leading-snug text-[#20251e] sm:text-3xl">{s.title}</h3>
                <p className="mt-3 max-w-md text-sm leading-6 text-[#687064]">{s.copy}</p>
                <div className="mt-5 max-w-md border-t border-[#dfe4da] pt-4 text-sm text-[#4f594a]">
                  ↳ {s.note}
                </div>
              </div>
            </article>
          ))}
        </section>

        {/* Tech stack panel */}
        <section id="stack" className="mx-auto max-w-6xl px-6 pb-24 lg:px-10">
          <div className="rounded-[28px] border border-[#dfe4da] bg-[#f7f9f4] px-8 py-14 text-center sm:px-16">
            <div className="mb-5 flex flex-wrap items-center justify-center gap-2 text-xs">
              {['Open Source', 'Self-hostable', 'Built to scale'].map((t) => (
                <span key={t} className="rounded-full bg-[#e9f1e0] px-3 py-1 font-medium text-[#4d6b2c]">{t}</span>
              ))}
            </div>
            <h2 className="text-2xl font-semibold text-[#20251e] sm:text-3xl">
              Built on modern, reliable technology.
            </h2>
            <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
              {techBadges.map((t) => (
                <span key={t} className="landing-tech-badge">{t}</span>
              ))}
            </div>
          </div>
        </section>

        {/* Footer CTA */}
        <footer className="mx-auto max-w-6xl px-6 pb-12 lg:px-10">
          <h2 className="max-w-md text-3xl font-semibold leading-tight text-[#20251e] sm:text-4xl">
            Your ideas.
            <br />
            Organized for good.
          </h2>
          <div className="mt-10 flex flex-wrap items-center gap-3 border-t border-[#dfe4da] pt-6 text-sm text-[#687064]">
            <a href="#" className="hover:text-[#20251e]">Privacy Policy</a>
            <span className="h-1 w-1 rounded-full bg-[#a8b1a2]" />
            <a href="#" className="hover:text-[#20251e]">Terms &amp; Conditions</a>
            <span className="h-1 w-1 rounded-full bg-[#a8b1a2]" />
            <a href="mailto:hello@notelite.app" className="hover:text-[#20251e]">hello@notelite.app</a>
          </div>
          <p className="mt-8 text-xs text-[#8a9385]">© 2026 NoteLite</p>
        </footer>
      </main>
    </div>
  )
}
