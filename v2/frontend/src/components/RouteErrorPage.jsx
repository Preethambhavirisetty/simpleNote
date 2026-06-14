import { Link, useRouteError } from 'react-router-dom'

export default function RouteErrorPage() {
  const error = useRouteError()

  return (
    <main className="flex min-h-screen items-center justify-center bg-[#f4f6f1] px-6 text-[#20251e]">
      <section className="w-full max-w-lg rounded-3xl border border-[#d9ded5] bg-white p-8 text-center shadow-xl">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#567c28]">NoteLite hit an issue</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">This page could not load.</h1>
        <p className="mt-3 text-sm leading-6 text-[#667061]">
          {error?.message || 'Please return to your notes and try again.'}
        </p>
        <Link to="/notes" className="mt-6 inline-flex rounded-full border border-[#567c28] bg-[#9ed858] px-5 py-2.5 text-sm font-semibold text-[#17220e]">
          Back to notes
        </Link>
      </section>
    </main>
  )
}
