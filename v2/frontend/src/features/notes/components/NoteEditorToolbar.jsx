import { useEffect, useRef, useState } from 'react'
import { DEFAULT_HIGHLIGHT_COLOR, FONT_OPTIONS, FONT_SIZE_OPTIONS } from '../noteEditorConfig'

const toolbarIconPaths = {
  bulletList: <><path d="M9 7h10M9 12h10M9 17h10" /><circle cx="5" cy="7" r="1" fill="currentColor" stroke="none" /><circle cx="5" cy="12" r="1" fill="currentColor" stroke="none" /><circle cx="5" cy="17" r="1" fill="currentColor" stroke="none" /></>,
  orderedList: <><path d="M10 7h9M10 12h9M10 17h9M4 6h2v3M4 12h2l-2 3h2M4 18h2" /></>,
  alignLeft: <path d="M4 6h16M4 10h11M4 14h16M4 18h9" />,
  alignCenter: <path d="M4 6h16M7 10h10M4 14h16M8 18h8" />,
  alignRight: <path d="M4 6h16M9 10h11M4 14h16M11 18h9" />,
  link: <><path d="M10 13a4 4 0 0 0 5.7.1l2.4-2.4A4 4 0 0 0 12.4 5L11 6.4" /><path d="M14 11a4 4 0 0 0-5.7-.1l-2.4 2.4A4 4 0 0 0 11.6 19l1.4-1.4" /></>,
  highlight: <><path d="m8 12 7-7 4 4-7 7H8v-4Z" /><path d="m14 6 4 4M5 20h14" /></>,
  clearFormatting: <><path d="M4 7V4h11M5 20h6M13 4 7 20M15 15l5 5m0-5-5 5" /></>,
}

function ToolbarIcon({ name }) {
  return <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{toolbarIconPaths[name]}</svg>
}

export default function NoteEditorToolbar({ editor }) {
  const [selectedFont, setSelectedFont] = useState('')
  const [selectedSize, setSelectedSize] = useState('')
  const [highlightColor, setHighlightColor] = useState(DEFAULT_HIGHLIGHT_COLOR)
  const [showLinkEditor, setShowLinkEditor] = useState(false)
  const [linkUrl, setLinkUrl] = useState('')
  const selectedFontRef = useRef('')
  const selectedSizeRef = useRef('')

  useEffect(() => {
    if (!editor) return
    const keepSelectedFormatting = () => {
      if (editor.isActive('codeBlock') || !editor.state.selection.empty) return
      const textStyle = editor.getAttributes('textStyle')
      if (selectedFontRef.current && textStyle.fontFamily !== selectedFontRef.current) editor.commands.setFontFamily(selectedFontRef.current)
      if (selectedSizeRef.current && textStyle.fontSize !== selectedSizeRef.current) editor.commands.setFontSize(selectedSizeRef.current)
    }
    editor.on('selectionUpdate', keepSelectedFormatting)
    return () => editor.off('selectionUpdate', keepSelectedFormatting)
  }, [editor])

  if (!editor) return null

  const controls = [
    ['B', 'Bold', () => editor.chain().focus().toggleBold().run(), editor.isActive('bold')],
    ['I', 'Italic', () => editor.chain().focus().toggleItalic().run(), editor.isActive('italic')],
    ['U', 'Underline', () => editor.chain().focus().toggleUnderline().run(), editor.isActive('underline')],
    ['H1', 'Heading 1', () => editor.chain().focus().toggleHeading({ level: 1 }).run(), editor.isActive('heading', { level: 1 })],
    ['H2', 'Heading 2', () => editor.chain().focus().toggleHeading({ level: 2 }).run(), editor.isActive('heading', { level: 2 })],
    [<ToolbarIcon key="bullet" name="bulletList" />, 'Bullet list', () => editor.chain().focus().toggleBulletList().run(), editor.isActive('bulletList')],
    [<ToolbarIcon key="ordered" name="orderedList" />, 'Numbered list', () => editor.chain().focus().toggleOrderedList().run(), editor.isActive('orderedList')],
    ['</>', 'Code', () => editor.chain().focus().toggleCodeBlock().run(), editor.isActive('codeBlock')],
  ]

  return (
    <div className="editor-toolbar workspace-scroll" role="toolbar" aria-label="Text formatting">
      <select value={selectedFont} onChange={(event) => {
        const value = event.target.value
        selectedFontRef.current = value
        setSelectedFont(value)
        if (value) editor.chain().focus().setFontFamily(value).run()
        else editor.chain().focus().unsetFontFamily().run()
      }} title="Font" className="editor-font-select">
        {FONT_OPTIONS.map(({ label, value }) => <option key={label} value={value} style={{ fontFamily: value || 'inherit' }}>{label}</option>)}
      </select>
      <select value={selectedSize} onChange={(event) => {
        const value = event.target.value
        selectedSizeRef.current = value
        setSelectedSize(value)
        if (value) editor.chain().focus().setFontSize(value).run()
        else editor.chain().focus().unsetFontSize().run()
      }} title="Text size" aria-label="Text size" className="editor-size-select">
        <option value="">Size</option>
        {FONT_SIZE_OPTIONS.map((size) => <option key={size} value={size}>{size.replace('px', '')}</option>)}
      </select>
      {controls.map(([label, title, action, active]) => <button type="button" key={title} onClick={action} aria-label={title} title={title} aria-pressed={active} className={active ? 'editor-tool-active' : ''}>{label}</button>)}
      <span className="editor-toolbar-divider" />
      {[['alignLeft', 'Align left', 'left'], ['alignCenter', 'Align center', 'center'], ['alignRight', 'Align right', 'right']].map(([icon, label, alignment]) => (
        <button type="button" key={alignment} onClick={() => editor.chain().focus().setTextAlign(alignment).run()} aria-label={label} title={label} aria-pressed={editor.isActive({ textAlign: alignment })} className={editor.isActive({ textAlign: alignment }) ? 'editor-tool-active' : ''}><ToolbarIcon name={icon} /></button>
      ))}
      <div className="editor-link-control">
        <button type="button" onClick={() => {
          if (editor.isActive('link')) {
            editor.chain().focus().unsetLink().run()
            setShowLinkEditor(false)
          } else {
            setLinkUrl('')
            setShowLinkEditor((open) => !open)
          }
        }} aria-label={editor.isActive('link') ? 'Remove link' : 'Insert link'} aria-pressed={editor.isActive('link')} className={editor.isActive('link') ? 'editor-tool-active' : ''}><ToolbarIcon name="link" /></button>
        {showLinkEditor && (
          <form className="editor-link-popover" onSubmit={(event) => {
            event.preventDefault()
            const value = linkUrl.trim()
            if (!value) return
            const href = /^[a-z][a-z\d+.-]*:/i.test(value) ? value : `https://${value}`
            editor.chain().focus().extendMarkRange('link').setLink({ href }).run()
            setShowLinkEditor(false)
            setLinkUrl('')
          }}>
            <input autoFocus type="text" inputMode="url" value={linkUrl} onChange={(event) => setLinkUrl(event.target.value)} placeholder="https://example.com" aria-label="Link URL" />
            <button type="submit">Apply</button>
          </form>
        )}
      </div>
      <label className={`editor-highlight-control ${editor.isActive('highlight') ? 'editor-tool-active' : ''}`} title="Highlight color">
        <ToolbarIcon name="highlight" />
        <span className="editor-highlight-swatch" style={{ backgroundColor: highlightColor }} />
        <input type="color" value={highlightColor} onChange={(event) => {
          const color = event.target.value
          setHighlightColor(color)
          editor.chain().focus().toggleHighlight({ color }).run()
        }} aria-label="Highlight color" />
      </label>
      <button
        type="button"
        onClick={() => editor.chain().focus().unsetAllMarks().clearNodes().run()}
        aria-label="Clear formatting"
        title="Clear formatting"
      >
        <ToolbarIcon name="clearFormatting" />
      </button>
    </div>
  )
}
