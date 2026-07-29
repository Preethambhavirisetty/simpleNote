export function parseNoteContent(raw) {
  if (raw && typeof raw === 'object' && raw.type === 'doc') return raw
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw)
      if (parsed?.type === 'doc') return parsed
    } catch {
      // Plain text is intentionally converted to TipTap paragraphs below.
    }
    return {
      type: 'doc',
      content: raw.split('\n').map((line) => ({
        type: 'paragraph',
        content: line ? [{ type: 'text', text: line }] : [],
      })),
    }
  }
  return { type: 'doc', content: [{ type: 'paragraph' }] }
}

export function textFromNoteContent(content) {
  if (typeof content === 'string') return content
  const parts = []
  const walk = (node) => {
    if (node?.text) parts.push(node.text)
    node?.content?.forEach(walk)
  }
  walk(content)
  return parts.join(' ')
}
