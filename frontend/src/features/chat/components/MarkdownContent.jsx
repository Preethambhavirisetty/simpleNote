import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export default function MarkdownContent({ content }) {
  return <div className="markdown-content"><ReactMarkdown remarkPlugins={[remarkGfm]}>{content || ''}</ReactMarkdown></div>
}
