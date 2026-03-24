import { useEffect, useRef, useState } from 'react'
import { useChatStore } from '@/stores/chatStore'

// ---------- Message bubble ----------

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
            : 'bg-zinc-800 text-zinc-200 rounded-bl-sm'
        }`}
      >
        {msg.isLoading ? (
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
          <span className="whitespace-pre-wrap">{msg.content}</span>
        )}
        {msg.isStreaming && !msg.isLoading && (
          <span className="ml-0.5 animate-pulse text-indigo-300">▋</span>
        )}
      </div>
    </div>
  )
}

// ---------- Mode toggle ----------

function ModeToggle({ mode, onChange }) {
  return (
    <div className="flex bg-zinc-800 rounded-lg p-0.5 text-xs">
      {[
        { key: 'rag', label: 'RAG' },
        { key: 'stream', label: 'Stream' },
      ].map(({ key, label }) => (
        <button
          key={key}
          onClick={() => onChange(key)}
          className={`px-3 py-1 rounded-md transition-colors ${
            mode === key ? 'bg-indigo-600 text-white' : 'text-zinc-400 hover:text-zinc-200'
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

// ---------- Page ----------

export default function ChatPage() {
  const messages = useChatStore((s) => s.messages)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const mode = useChatStore((s) => s.mode)
  const setMode = useChatStore((s) => s.setMode)
  const sendRagMessage = useChatStore((s) => s.sendRagMessage)
  const sendStreamMessage = useChatStore((s) => s.sendStreamMessage)
  const clearMessages = useChatStore((s) => s.clearMessages)

  const [input, setInput] = useState('')
  const bottomRef = useRef(null)
  const textareaRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = async () => {
    const text = input.trim()
    if (!text || isStreaming) return
    setInput('')
    textareaRef.current?.focus()

    if (mode === 'rag') {
      await sendRagMessage(text)
    } else {
      await sendStreamMessage(text)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-3 border-b border-zinc-800 flex items-center justify-between">
        <div>
          <h1 className="text-sm font-medium text-zinc-200">Chat</h1>
          <p className="text-xs text-zinc-500">
            {mode === 'rag' ? 'RAG — retrieves context from your notes' : 'Stream — direct model completions'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ModeToggle mode={mode} onChange={setMode} />
          <button
            onClick={clearMessages}
            className="text-xs text-zinc-600 hover:text-zinc-300 px-2 py-1 rounded transition-colors"
          >
            Clear
          </button>
        </div>
      </div>

      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center gap-2">
            <p className="text-zinc-500 text-sm">Ask anything about your notes</p>
            <p className="text-zinc-600 text-xs max-w-xs">
              RAG retrieves relevant context first · Stream sends directly to the model
            </p>
          </div>
        )}
        {messages.map((msg) => (
          <Message key={msg.id} msg={msg} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-6 py-4 border-t border-zinc-800">
        <div className="flex gap-3 items-end">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question… (Enter to send · Shift+Enter for newline)"
            rows={1}
            className="flex-1 bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-indigo-500 resize-none transition-colors"
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
  )
}
