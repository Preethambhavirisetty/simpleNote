export function NoteEditorWelcome() {
  return (
    <section className="note-editor-panel items-center justify-center text-center">
      <div className="editor-welcome-icon">✦</div>
      <p className="workspace-faint mt-6 text-caption font-semibold uppercase tracking-[0.18em]">A quiet place to think</p>
      <h2 className="workspace-secondary mt-3 font-semibold tracking-[-0.04em]">Pick a note and start writing.</h2>
      <p className="workspace-muted mt-3 max-w-sm text-sm leading-6">Select a card from the left or create a new note. Changes save automatically as you write.</p>
    </section>
  )
}

export function NoteEditorLoading({ error, onRetry }) {
  return (
    <section className="note-editor-panel items-center justify-center text-center" aria-live="polite">
      {error ? (
        <>
          <p className="note-save-error">{error}</p>
          <button onClick={onRetry} className="note-load-retry">Try again</button>
        </>
      ) : (
        <>
          <span className="note-spinner" />
          <p className="workspace-muted mt-4 text-sm">Opening note…</p>
        </>
      )}
    </section>
  )
}
