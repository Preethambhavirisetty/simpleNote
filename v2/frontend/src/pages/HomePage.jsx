import { Link } from 'react-router-dom'
import noteliteIcon from '@/assets/notelite_icon.png'

const features = [
  {
    title: 'Write without friction',
    copy: 'A calm, flexible editor for quick thoughts, long-form notes, and everything between.',
    icon: '✦',
  },
  {
    title: 'Ask your notes',
    copy: 'Turn your personal knowledge into clear answers with conversations grounded in your writing.',
    icon: '⌁',
  },
  {
    title: 'Keep ideas connected',
    copy: 'Folders, tags, and intelligent retrieval keep the right context close when you need it.',
    icon: '◎',
  },
]

export default function HomePage() {
  return (
    <div className="landing-page min-h-screen overflow-hidden bg-[#f4f6f1] text-[#20251e]">
      <div className="landing-glow landing-glow-one" />
      <div className="landing-glow landing-glow-two" />

      <header className="relative z-10 mx-auto flex max-w-7xl items-center justify-between px-6 py-6 lg:px-10">
        <Link to="/" className="flex items-center gap-2.5">
          <img src={noteliteIcon} alt="" className="h-10 w-10 rounded-xl" />
          <span className="text-lg font-semibold tracking-tight">NoteLite</span>
        </Link>

        <nav className="hidden items-center gap-8 text-sm text-[#667061] md:flex">
          <a href="#features" className="hover:text-[#20251e]">Features</a>
          <a href="#workflow" className="hover:text-[#20251e]">How it works</a>
          <a href="#about" className="hover:text-[#20251e]">About</a>
        </nav>

        <div className="flex items-center gap-2">
          <Link to="/login" className="rounded-full px-4 py-2 text-sm text-[#566151] hover:bg-black/[0.04] hover:text-[#20251e]">
            Sign in
          </Link>
          <Link to="/register" className="rounded-full bg-[#9ed858] px-5 py-2.5 text-sm font-semibold text-[#17220e] shadow-sm hover:bg-[#ace567]">
            Get started
          </Link>
        </div>
      </header>

      <main className="relative z-10">
        <section className="mx-auto grid min-h-[76vh] max-w-7xl items-center gap-14 px-6 pb-20 pt-14 lg:grid-cols-[1.02fr_0.98fr] lg:px-10 lg:pt-20">
          <div className="max-w-2xl">
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-[#567c28]/20 bg-[#9ed858]/15 px-3 py-1.5 text-xs font-medium text-[#567c28]">
              <span className="h-1.5 w-1.5 rounded-full bg-[#78a83f]" />
              Your notes, now more useful
            </div>
            <h1 className="text-5xl font-semibold leading-[1.02] tracking-[-0.055em] sm:text-6xl lg:text-7xl">
              Think clearly.
              <span className="block text-[#929b8d]">Remember everything.</span>
            </h1>
            <p className="mt-7 max-w-xl text-base leading-7 text-[#667061] sm:text-lg">
              NoteLite brings focused writing and intelligent conversation into one private workspace,
              so your best ideas never get buried.
            </p>
            <div className="mt-9 flex flex-wrap items-center gap-3">
              <Link to="/register" className="rounded-full bg-[#9ed858] px-6 py-3 text-sm font-semibold text-[#17220e] shadow-[0_12px_35px_rgba(86,124,40,0.15)] hover:bg-[#ace567]">
                Start writing free
              </Link>
              <Link to="/login" className="rounded-full border border-black/10 bg-white/70 px-6 py-3 text-sm font-medium text-[#35402f] shadow-sm hover:bg-white">
                Open your workspace
              </Link>
            </div>
            <div className="mt-10 flex items-center gap-5 text-xs text-[#7b8476]">
              <span>No credit card</span>
              <span className="h-1 w-1 rounded-full bg-[#b2b9ad]" />
              <span>Built for focused thinking</span>
              <span className="h-1 w-1 rounded-full bg-[#b2b9ad]" />
              <span>AI grounded in your notes</span>
            </div>
          </div>

          <WorkspacePreview />
        </section>

        <section id="features" className="mx-auto max-w-7xl px-6 pb-24 lg:px-10">
          <div className="grid gap-4 md:grid-cols-3">
            {features.map((feature) => (
              <article key={feature.title} className="rounded-[28px] border border-black/[0.07] bg-white/70 p-6 shadow-[0_18px_50px_rgba(46,58,38,0.06)] backdrop-blur">
                <div className="mb-8 flex h-11 w-11 items-center justify-center rounded-2xl bg-[#9ed858]/20 text-lg text-[#567c28]">
                  {feature.icon}
                </div>
                <h2 className="text-lg font-medium">{feature.title}</h2>
                <p className="mt-2 text-sm leading-6 text-[#667061]">{feature.copy}</p>
              </article>
            ))}
          </div>
        </section>
      </main>
    </div>
  )
}

function WorkspacePreview() {
  return (
    <div className="relative mx-auto w-full max-w-xl">
      <div className="absolute -inset-6 rounded-[40px] bg-[#9ed858]/15 blur-2xl" />
      <div className="relative overflow-hidden rounded-[30px] border border-black/10 bg-white/80 p-3 shadow-[0_30px_80px_rgba(46,58,38,0.16)]">
        <div className="flex min-h-[480px] overflow-hidden rounded-[22px] border border-black/[0.07] bg-white">
          <div className="hidden w-36 shrink-0 border-r border-black/[0.07] bg-[#f2f5ef] p-3 sm:block">
            <div className="mb-8 flex items-center gap-2 text-xs font-semibold">
              <div className="h-5 w-5 rounded-lg bg-[#b8ff67]" />
              NoteLite
            </div>
            <div className="rounded-lg bg-[#9ed858] px-3 py-2 text-xs font-semibold text-[#17220e]">+ New chat</div>
            <div className="mt-6 space-y-3 text-xs text-[#7b8476]">
              <p className="text-[#35402f]">Explore notes</p>
              <p>All notes</p>
              <p>Favorites</p>
              <p>Settings</p>
            </div>
            <p className="mb-3 mt-8 text-xs uppercase tracking-widest text-[#929b8d]">Recent chats</p>
            <div className="space-y-3 text-xs text-[#7b8476]">
              <p className="truncate text-[#567c28]">Plan the product launch</p>
              <p className="truncate">Summarize research ideas</p>
              <p className="truncate">Weekly reflections</p>
            </div>
          </div>
          <div className="flex flex-1 flex-col p-5">
            <div className="flex items-center justify-between border-b border-black/[0.07] pb-4">
              <div>
                <p className="text-xs text-[#929b8d]">Conversation</p>
                <p className="mt-1 text-xs">Plan the product launch</p>
              </div>
              <div className="h-7 w-7 rounded-full bg-[#9ed858]/30" />
            </div>
            <div className="flex-1 space-y-5 pt-6">
              <div className="ml-auto max-w-[78%] rounded-2xl rounded-br-sm bg-[#f1f4ee] px-3 py-2.5 text-xs leading-4 text-[#566151]">
                Pull together the strongest launch ideas from my notes.
              </div>
              <div className="max-w-[88%] text-xs leading-4 text-[#667061]">
                <p className="mb-2 text-[#35402f]">Here is a focused launch plan based on your notes:</p>
                <div className="space-y-2 rounded-xl border border-black/[0.06] bg-[#f7f9f5] p-3">
                  <p><span className="text-[#567c28]">01</span> Lead with the personal knowledge story.</p>
                  <p><span className="text-[#567c28]">02</span> Show the writing-to-answer workflow.</p>
                  <p><span className="text-[#567c28]">03</span> Invite early users into a focused beta.</p>
                </div>
              </div>
            </div>
            <div className="rounded-2xl border border-black/[0.07] bg-[#f4f6f2] p-3">
              <p className="text-xs text-[#929b8d]">Ask anything about your notes...</p>
              <div className="mt-3 flex justify-between">
                <div className="flex gap-1.5">
                  <span className="rounded-full bg-white px-2 py-1 text-xs text-[#7b8476]">Brainstorm</span>
                  <span className="rounded-full bg-white px-2 py-1 text-xs text-[#7b8476]">Summarize</span>
                </div>
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[#9ed858] text-xs text-[#17220e]">↑</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
