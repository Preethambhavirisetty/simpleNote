import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { useAuthStore } from '@/stores/authStore'
import { useChatStore } from '@/stores/chatStore'

const prompts = [
  ['Summarize', 'Summarize the key ideas across my notes'],
  ['Connect ideas', 'Find useful connections between my notes'],
  ['Plan', 'Turn my recent notes into an action plan'],
]

export default function ChatPage() {
  const { conversationId } = useParams()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const conversations = useChatStore((s) => s.conversations)
  const activeConvId = useChatStore((s) => s.activeConvId)
  const messages = useChatStore((s) => s.messages)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const isLoadingMessages = useChatStore((s) => s.isLoadingMessages)
  const selectConversation = useChatStore((s) => s.selectConversation)
  const newConversation = useChatStore((s) => s.newConversation)
  const sendMessage = useChatStore((s) => s.sendMessage)

  const [input, setInput] = useState('')
  const bottomRef = useRef(null)
  const textareaRef = useRef(null)
  const activeConversation = conversations.find((item) => String(item.id) === String(activeConvId))

  useEffect(() => {
    if (conversationId) selectConversation(conversationId)
    else if (activeConvId) newConversation()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId])

  useEffect(() => {
    if (activeConvId && String(activeConvId) !== String(conversationId)) {
      navigate(`/chat/${activeConvId}`, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeConvId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = async (suggestion) => {
    const text = (suggestion ?? input).trim()
    if (!text || isStreaming) return
    setInput('')
    await sendMessage(text)
    textareaRef.current?.focus()
  }

  return (
    <div className="chat-workspace flex h-full min-w-0 flex-col overflow-hidden">
      <header className="workspace-border flex h-[74px] shrink-0 items-center justify-between border-b px-6 lg:px-8">
        <div className="min-w-0">
          <p className="workspace-faint text-[10px] font-semibold uppercase tracking-[0.15em]">Conversation</p>
          <h1 className="workspace-primary mt-1 truncate text-sm font-medium">
            {activeConversation?.title || 'New conversation'}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <button className="chat-header-button">Share</button>
          <button className="chat-header-icon" aria-label="More options">•••</button>
        </div>
      </header>

      <div className="workspace-scroll flex-1 overflow-y-auto">
        {isLoadingMessages ? (
          <div className="flex h-full items-center justify-center">
            <span className="h-5 w-5 animate-spin rounded-full border-2 border-[#b8ff67]/20 border-t-[#b8ff67]" />
          </div>
        ) : messages.length === 0 ? (
          <EmptyState user={user} onPrompt={handleSend} />
        ) : (
          <div className="mx-auto max-w-4xl px-5 pb-32 pt-8 sm:px-8">
            {messages.map((message) => <Message key={message.id} message={message} user={user} />)}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      <div className="chat-composer-fade pointer-events-none absolute inset-x-0 bottom-0 z-10 px-4 pb-5 pt-14 sm:px-7">
        <Composer
          input={input}
          setInput={setInput}
          textareaRef={textareaRef}
          isStreaming={isStreaming}
          onSend={() => handleSend()}
        />
      </div>
    </div>
  )
}

function EmptyState({ user, onPrompt }) {
  const firstName = user?.name?.split(' ')[0]
  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col items-center justify-center px-6 pb-24 text-center">
      <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-[22px] border border-[#b8ff67]/20 bg-[#b8ff67]/10 text-2xl text-[#b8ff67] shadow-[0_0_50px_rgba(184,255,103,0.08)]">✦</div>
      <p className="text-xs font-medium uppercase tracking-[0.17em] text-[#b8ff67]">Your knowledge workspace</p>
      <h2 className="workspace-primary mt-3 text-3xl font-medium tracking-[-0.035em] sm:text-4xl">
        What are we thinking about{firstName ? `, ${firstName}` : ''}?
      </h2>
      <p className="workspace-muted mt-3 max-w-lg text-sm leading-6">
        Ask a question and NoteLite will find useful context across your notes before answering.
      </p>
      <div className="mt-9 grid w-full gap-3 sm:grid-cols-3">
        {prompts.map(([title, prompt]) => (
          <button key={title} onClick={() => onPrompt(prompt)} className="workspace-card rounded-2xl p-4 text-left">
            <span className="workspace-primary block text-xs font-medium">{title}</span>
            <span className="workspace-faint mt-1.5 block text-[11px] leading-5">{prompt}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function Message({ message, user }) {
  const isUser = message.role === 'user'
  const initials = user?.name?.[0]?.toUpperCase() ?? user?.email?.[0]?.toUpperCase() ?? 'Y'

  if (isUser) {
    return (
      <div className="mb-8 flex items-start justify-end gap-3">
        <div className="workspace-card workspace-primary max-w-[78%] rounded-2xl rounded-tr-sm px-4 py-3 text-sm leading-6">
          {message.content}
        </div>
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#b8ff67] text-[11px] font-semibold text-[#10140d]">{initials}</span>
      </div>
    )
  }

  return (
    <div className="mb-10 flex items-start gap-3">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-[#b8ff67]/20 bg-[#b8ff67]/10 text-xs text-[#b8ff67]">✦</span>
      <div className={`min-w-0 flex-1 pt-1 text-sm leading-7 ${message.isError ? 'text-red-400' : 'workspace-primary'}`}>
        {message.isStreaming && !message.content ? (
          <span className="flex h-6 items-center gap-1">
            {[0, 150, 300].map((delay) => <span key={delay} className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#b8ff67]" style={{ animationDelay: `${delay}ms` }} />)}
          </span>
        ) : (
          <div className="chat-markdown"><ReactMarkdown>{message.content}</ReactMarkdown></div>
        )}
        {message.isStreaming && message.content && <span className="animate-pulse text-[#b8ff67]">▋</span>}
        {!message.isStreaming && !message.isError && (
          <div className="workspace-faint mt-3 flex gap-2 text-[10px]">
            <button className="workspace-pill rounded-full px-2.5 py-1">Copy</button>
            {message.sources?.length > 0 && <span className="workspace-pill rounded-full px-2.5 py-1">{message.sources.length} sources</span>}
          </div>
        )}
      </div>
    </div>
  )
}

function Composer({ input, setInput, textareaRef, isStreaming, onSend }) {
  const handleKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      onSend()
    }
  }

  return (
    <div className="chat-composer pointer-events-auto mx-auto max-w-4xl rounded-[22px] p-3 shadow-2xl">
      <textarea
        ref={textareaRef}
        value={input}
        onChange={(event) => setInput(event.target.value)}
        onKeyDown={handleKeyDown}
        rows={1}
        placeholder="Ask anything about your notes..."
        className="workspace-primary max-h-36 min-h-[48px] w-full resize-none bg-transparent px-2 py-2 text-sm leading-6 outline-none placeholder:text-zinc-500"
      />
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-1.5 overflow-x-auto">
          {['Brainstorm', 'Summarize', 'Plan'].map((item) => <span key={item} className="workspace-pill workspace-muted whitespace-nowrap rounded-full px-3 py-1.5 text-[10px]">{item}</span>)}
        </div>
        <button onClick={onSend} disabled={isStreaming || !input.trim()} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#b8ff67] text-sm font-semibold text-[#10140d] hover:bg-[#ccff8f] disabled:opacity-30">
          {isStreaming ? <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-black/20 border-t-black" /> : '↑'}
        </button>
      </div>
    </div>
  )
}
