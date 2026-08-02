import { ChatBubbleIcon } from './ChatIcons'

export default function ChatEmptyState() {
  return (
    <div className="chat-empty-state">
      <div className="chat-empty-icon"><ChatBubbleIcon className="h-6 w-6" /></div>
      <div>
        <p className="chat-empty-title">Ask anything about your notes</p>
        <p className="chat-empty-description">Your questions are answered using context retrieved from your notes.</p>
      </div>
    </div>
  )
}
