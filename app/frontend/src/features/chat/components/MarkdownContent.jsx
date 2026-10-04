import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const ALLOWED_ELEMENTS = [
  'a', 'blockquote', 'br', 'code', 'del', 'em', 'h1', 'h2', 'h3', 'h4', 'h5',
  'h6', 'hr', 'input', 'li', 'ol', 'p', 'pre', 'strong', 'table', 'tbody', 'td',
  'th', 'thead', 'tr', 'ul',
]

export default function MarkdownContent({ content }) {
  return <div className="markdown-content"><ReactMarkdown allowedElements={ALLOWED_ELEMENTS} remarkPlugins={[remarkGfm]}>{content || ''}</ReactMarkdown></div>
}
