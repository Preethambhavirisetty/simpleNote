import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import ChatComposer from '@/features/chat/components/ChatComposer'
import ChatEmptyState from '@/features/chat/components/ChatEmptyState'
import ChatHeader from '@/features/chat/components/ChatHeader'
import ChatMessage from '@/features/chat/components/ChatMessage'
import ConversationSidebar from '@/features/chat/components/ConversationSidebar'
import { useChatStore } from '@/stores/chatStore'
import { useFeatureFlagStore } from '@/stores/featureFlagStore'

export default function ChatPage() {
  const { conversationId } = useParams()
  const navigate = useNavigate()
  const isHistoryEnabled = useFeatureFlagStore((s) => s.isEnabled)('chat.history')
  const conversations = useChatStore((s) => s.conversations)
  const activeConversationId = useChatStore((s) => s.activeConvId)
  const messages = useChatStore((s) => s.messages)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const isLoadingConversations = useChatStore((s) => s.isLoadingConvs)
  const isLoadingMessages = useChatStore((s) => s.isLoadingMessages)
  const fetchConversations = useChatStore((s) => s.fetchConversations)
  const selectConversation = useChatStore((s) => s.selectConversation)
  const newConversation = useChatStore((s) => s.newConversation)
  const deleteConversation = useChatStore((s) => s.deleteConversation)
  const sendMessage = useChatStore((s) => s.sendMessage)
  const cancelStream = useChatStore((s) => s.cancelStream)
  const [input, setInput] = useState('')
  const bottomRef = useRef(null)

  useEffect(() => { fetchConversations() }, [fetchConversations])

  // Follow URL changes only. SSE meta updates the store before navigation catches up.
  useEffect(() => {
    if (conversationId) selectConversation(conversationId)
    else newConversation()
  }, [conversationId, newConversation, selectConversation])
  // A newly streamed conversation starts at /chat and receives its ID from
  // SSE metadata. Existing conversation URLs remain the source of truth.
  useEffect(() => {
    if (isStreaming && activeConversationId && !conversationId) navigate(`/chat/${activeConversationId}`, { replace: true })
  }, [activeConversationId, conversationId, isStreaming, navigate])
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      bottomRef.current?.scrollIntoView({ behavior: isStreaming ? 'auto' : 'smooth' })
    })
    return () => cancelAnimationFrame(frame)
  }, [isStreaming, messages])
  useEffect(() => () => cancelStream(), [cancelStream])

  const handleSend = async () => {
    const text = input.trim()
    if (!text || isStreaming) return
    setInput('')
    await sendMessage(text)
  }
  const handleDeleteConversation = async (id) => {
    await deleteConversation(id)
    if (activeConversationId === id) navigate('/chat', { replace: true })
  }

  return (
    <div className="flex h-full">
      {isHistoryEnabled && <ConversationSidebar conversations={conversations} activeConversationId={activeConversationId} isLoading={isLoadingConversations} onSelect={(id) => navigate(`/chat/${id}`)} onNew={() => navigate('/chat')} onDelete={handleDeleteConversation} />}
      <section className="chat-panel">
        <ChatHeader hasActiveConversation={Boolean(activeConversationId)} />
        <div className="chat-message-list">
          {isLoadingMessages && <div className="flex h-full items-center justify-center"><span className="chat-loading-spinner" /></div>}
          {!isLoadingMessages && messages.length === 0 && <ChatEmptyState />}
          {!isLoadingMessages && messages.map((message) => <ChatMessage key={message.id} message={message} />)}
          <div ref={bottomRef} />
        </div>
        <ChatComposer input={input} isStreaming={isStreaming} onInputChange={setInput} onSend={handleSend} onCancel={cancelStream} />
      </section>
    </div>
  )
}
