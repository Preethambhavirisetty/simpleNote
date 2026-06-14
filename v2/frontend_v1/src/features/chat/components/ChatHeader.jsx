export default function ChatHeader({ hasActiveConversation }) {
  return (
    <header className="chat-header">
      <h1 className="chat-header-title">Chat</h1>
      <p className="chat-header-description">
        {hasActiveConversation ? 'Continuing conversation' : 'New conversation - retrieves context from your notes'}
      </p>
    </header>
  )
}
