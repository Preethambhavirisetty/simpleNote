import { ChatBubbleIcon, PlusIcon, TrashIcon } from './ChatIcons'

export default function ConversationSidebar({ conversations, activeConversationId, isLoading, onSelect, onNew, onDelete }) {
  return (
    <aside className="chat-sidebar">
      <div className="chat-sidebar-header"><button type="button" onClick={onNew} className="chat-new-button"><PlusIcon />New Chat</button></div>
      <div className="flex-1 space-y-0.5 overflow-y-auto px-2 py-2">
        {isLoading && conversations.length === 0 && <p className="chat-sidebar-status">Loading...</p>}
        {!isLoading && conversations.length === 0 && <p className="chat-sidebar-status">No conversations yet</p>}
        {conversations.map((conversation) => (
          <div key={conversation.id} className={`chat-conversation ${activeConversationId === conversation.id ? 'chat-conversation-active' : ''}`} onClick={() => onSelect(conversation.id)}>
            <ChatBubbleIcon />
            <span className="flex-1 truncate">{conversation.title || 'Untitled'}</span>
            <button type="button" onClick={(event) => { event.stopPropagation(); onDelete(conversation.id) }} className="chat-delete-button" title="Delete conversation"><TrashIcon /></button>
          </div>
        ))}
      </div>
    </aside>
  )
}
