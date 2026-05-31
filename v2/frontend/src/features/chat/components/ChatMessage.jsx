import ChatMessageReferences from './ChatMessageReferences'
import MarkdownContent from './MarkdownContent'

function StreamingIndicator() {
  return <span className="flex h-4 items-center gap-1">{[0, 150, 300].map((delay) => <span key={delay} className="chat-streaming-dot" style={{ animationDelay: `${delay}ms` }} />)}</span>
}

export default function ChatMessage({ message }) {
  const isUser = message.role === 'user'
  const bubbleClass = isUser ? 'chat-message-bubble chat-user-message' : message.isError ? 'chat-message-bubble chat-error-message' : 'chat-message-bubble chat-assistant-message'

  return (
    <article className={`mb-4 flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={bubbleClass}>
        {message.isStreaming && !message.content ? <StreamingIndicator /> : isUser ? <p className="whitespace-pre-wrap">{message.content}</p> : <MarkdownContent content={message.content} />}
        {message.isStreaming && message.content && <span className="chat-streaming-cursor">|</span>}
        {!isUser && !message.isStreaming && <ChatMessageReferences references={message.references} />}
      </div>
    </article>
  )
}
