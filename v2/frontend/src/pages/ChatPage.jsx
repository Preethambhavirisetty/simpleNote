import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useChatStore } from '@/stores/chatStore'
import ReactMarkdown from 'react-markdown'

// ── Icons ────────────────────────────────────────────────────────────────────

function PlusIcon() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
    </svg>
  )
}

function TrashIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
    </svg>
  )
}

function ChatBubbleIcon() {
  return (
    <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
    </svg>
  )
}

// ── Message bubble ───────────────────────────────────────────────────────────

function Message({ msg }) {
  const isUser = msg.role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div
        className={`max-w-[72%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? 'bg-indigo-600 text-white rounded-br-sm'
            : msg.isError
            ? 'bg-red-950/50 border border-red-900/40 text-red-300 rounded-bl-sm'
            : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-800 dark:text-zinc-200 rounded-bl-sm'
        }`}
      >
        {msg.isStreaming && !msg.content ? (
          <span className="flex gap-1 items-center h-4">
            {[0, 150, 300].map((d) => (
              <span
                key={d}
                className="w-1.5 h-1.5 bg-zinc-500 rounded-full animate-bounce"
                style={{ animationDelay: `${d}ms` }}
              />
            ))}
          </span>
        ) : (
          <div className="prose prose-sm prose-zinc dark:prose-invert max-w-none">
            <ReactMarkdown>{msg.content}</ReactMarkdown>
          </div>
        )}
        {msg.isStreaming && msg.content && (
          <span className="ml-0.5 animate-pulse text-indigo-300">▋</span>
        )}
      </div>
    </div>
  )
}

// ── Conversation sidebar ─────────────────────────────────────────────────────

function ConversationSidebar({ conversations, activeConvId, isLoading, onSelect, onNew, onDelete }) {
  return (
    <div className="w-60 flex flex-col border-r border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/50 shrink-0 h-full">
      <div className="px-3 py-3 border-b border-zinc-200 dark:border-zinc-800">
        <button
          onClick={onNew}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-medium bg-indigo-600 hover:bg-indigo-500 text-white transition-colors"
        >
          <PlusIcon />
          New Chat
        </button>
      </div>

      <div className="flex-1 overflow-y-auto py-2 px-2 space-y-0.5">
        {isLoading && conversations.length === 0 && (
          <p className="text-xs text-zinc-500 text-center py-4">Loading…</p>
        )}
        {!isLoading && conversations.length === 0 && (
          <p className="text-xs text-zinc-500 text-center py-4">No conversations yet</p>
        )}
        {conversations.map((conv) => (
          <div
            key={conv.id}
            className={`group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
              activeConvId === conv.id
                ? 'bg-indigo-600/10 dark:bg-indigo-600/20 text-indigo-600 dark:text-indigo-300'
                : 'text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800'
            }`}
            onClick={() => onSelect(conv.id)}
          >
            <ChatBubbleIcon />
            <span className="text-sm truncate flex-1">{conv.title || 'Untitled'}</span>
            <button
              onClick={(e) => {
                e.stopPropagation()
                onDelete(conv.id)
              }}
              className="opacity-0 group-hover:opacity-100 text-zinc-400 hover:text-red-400 shrink-0 p-0.5 rounded transition-all"
              title="Delete conversation"
            >
              <TrashIcon />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Empty state ──────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center gap-3">
      <div className="w-12 h-12 rounded-full bg-indigo-600/10 dark:bg-indigo-600/20 flex items-center justify-center">
        <svg className="w-6 h-6 text-indigo-500" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
        </svg>
      </div>
      <div>
        <p className="text-zinc-600 dark:text-zinc-400 text-sm font-medium">Ask anything about your notes</p>
        <p className="text-zinc-400 dark:text-zinc-600 text-xs mt-1 max-w-xs">
          Your questions are answered using context retrieved from your notes
        </p>
      </div>
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function ChatPage() {
  const { conversationId } = useParams()
  const navigate = useNavigate()

  const conversations = useChatStore((s) => s.conversations)
  const activeConvId = useChatStore((s) => s.activeConvId)
  const messages = useChatStore((s) => s.messages)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const isLoadingConvs = useChatStore((s) => s.isLoadingConvs)
  const isLoadingMessages = useChatStore((s) => s.isLoadingMessages)
  const fetchConversations = useChatStore((s) => s.fetchConversations)
  const selectConversation = useChatStore((s) => s.selectConversation)
  const newConversation = useChatStore((s) => s.newConversation)
  const deleteConversation = useChatStore((s) => s.deleteConversation)
  const sendMessage = useChatStore((s) => s.sendMessage)

  const [input, setInput] = useState('')
  const bottomRef = useRef(null)
  const textareaRef = useRef(null)

  useEffect(() => {
    fetchConversations()
  }, [fetchConversations])

  // URL → store sync: load conversation when URL changes
  useEffect(() => {
    if (conversationId) {
      selectConversation(conversationId)
    } else if (activeConvId) {
      newConversation()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId])

  // Store → URL sync: update URL when a new conversation is created via streaming
  useEffect(() => {
    if (activeConvId && activeConvId !== conversationId) {
      navigate(`/chat/${activeConvId}`, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeConvId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = async () => {
    const text = input.trim()
    if (!text || isStreaming) return
    setInput('')
    textareaRef.current?.focus()
    await sendMessage(text)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleSelectConv = (convId) => {
    navigate(`/chat/${convId}`)
  }

  const handleNewChat = () => {
    navigate('/chat')
  }

  const handleDeleteConv = async (convId) => {
    await deleteConversation(convId)
    if (activeConvId === convId) {
      navigate('/chat', { replace: true })
    }
  }

  return (
    <div className="flex h-full">
      {/* Conversation sidebar */}
      <ConversationSidebar
        conversations={conversations}
        activeConvId={activeConvId}
        isLoading={isLoadingConvs}
        onSelect={handleSelectConv}
        onNew={handleNewChat}
        onDelete={handleDeleteConv}
      />

      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="px-6 py-3 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between shrink-0">
          <div>
            <h1 className="text-sm font-medium text-zinc-800 dark:text-zinc-200">Chat</h1>
            <p className="text-xs text-zinc-500">
              {activeConvId ? 'Continuing conversation' : 'New conversation — retrieves context from your notes'}
            </p>
          </div>
        </div>

        {/* Message list */}
        <div className="flex-1 overflow-y-auto px-6 py-6">
          {isLoadingMessages && (
            <div className="flex items-center justify-center h-full">
              <span className="w-5 h-5 border-2 border-indigo-500/30 border-t-indigo-500 rounded-full animate-spin" />
            </div>
          )}
          {!isLoadingMessages && messages.length === 0 && <EmptyState />}
          {!isLoadingMessages &&
            messages.map((msg) => <Message key={msg.id} msg={msg} />)}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="px-6 py-4 border-t border-zinc-200 dark:border-zinc-800 shrink-0">
          <div className="flex gap-3 items-end">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question… (Enter to send · Shift+Enter for newline)"
              rows={1}
              className="flex-1 bg-zinc-100 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl px-4 py-3 text-sm text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 dark:placeholder-zinc-600 focus:outline-none focus:border-indigo-500 resize-none transition-colors"
              style={{ maxHeight: '180px', overflowY: 'auto' }}
            />
            <button
              onClick={handleSend}
              disabled={isStreaming || !input.trim()}
              className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white rounded-xl px-4 py-3 text-sm font-medium transition-colors shrink-0"
            >
              {isStreaming ? (
                <span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin block" />
              ) : (
                'Send'
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
