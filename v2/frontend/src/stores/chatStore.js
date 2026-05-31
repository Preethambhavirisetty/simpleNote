import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import { conversationsApi } from '@/api/conversations'
import { streamChat } from '@/api/agent'
import { useAuthStore } from './authStore'

let activeStreamController = null

export const useChatStore = create(
  devtools(
    (set, get) => ({
      conversations: [],
      activeConvId: null,
      messages: [],
      isStreaming: false,
      isLoadingConvs: false,
      isLoadingMessages: false,
      error: null,

      // ── Conversation list ──────────────────────────────────────────

      fetchConversations: async () => {
        if (get().isLoadingConvs) return
        set({ isLoadingConvs: true })
        try {
          const list = await conversationsApi.list({ limit: 100 })
          set({ conversations: list, isLoadingConvs: false })
        } catch (err) {
          console.error('[chatStore] fetchConversations failed:', err)
          set({ isLoadingConvs: false })
        }
      },

      selectConversation: async (convId) => {
        if (get().activeConvId === convId) return
        _cancelActiveStream(set)
        set({ activeConvId: convId, messages: [], isLoadingMessages: true, error: null })
        try {
          const conv = await conversationsApi.get(convId)
          const msgs = (conv.messages ?? []).map((m) => {
            const raw = m.sources_used
            const hasRichSources = Array.isArray(raw) && raw.length > 0 && typeof raw[0] === 'object'
            return {
              id: m.id,
              role: m.role,
              content: m.content,
              timestamp: m.created_at,
              sources: hasRichSources ? raw.map((s) => s.note_id) : raw,
              citations: hasRichSources ? raw : undefined,
            }
          })
          set({ messages: msgs, isLoadingMessages: false })
        } catch (err) {
          console.error('[chatStore] selectConversation failed:', err)
          set({ isLoadingMessages: false, error: 'Failed to load conversation' })
        }
      },

      newConversation: () => {
        _cancelActiveStream(set)
        set({ activeConvId: null, messages: [], error: null })
      },

      deleteConversation: async (convId) => {
        try {
          await conversationsApi.delete(convId)
          const { activeConvId } = get()
          set((s) => ({
            conversations: s.conversations.filter((c) => c.id !== convId),
            ...(activeConvId === convId ? { activeConvId: null, messages: [] } : {}),
          }))
        } catch {
          // silent
        }
      },

      // ── Streaming chat ─────────────────────────────────────────────

      cancelStream: () => _cancelActiveStream(set),

      sendMessage: async (query) => {
        _cancelActiveStream(set)
        const { user } = useAuthStore.getState()
        if (!user) return

        const { activeConvId, messages } = get()
        const userMsg = _makeMsg('user', query)
        const assistantMsg = _makeMsg('assistant', '', { isStreaming: true })

        set((s) => ({
          messages: [...s.messages, userMsg, assistantMsg],
          isStreaming: true,
          error: null,
        }))

        const body = {
          query,
          k: 5,
          user_id: user.id,
          role: user.roles?.includes('admin') ? 'admin' : 'user',
          tenant_id: user.id,
          conversation_id: activeConvId || undefined,
          conversation_title: !activeConvId && messages.length === 0 ? query.slice(0, 100) : undefined,
        }

        const streamController = new AbortController()
        activeStreamController = streamController

        await streamChat({
          body,
          signal: streamController.signal,
          onMeta: (meta) => {
            const convId = meta.conversation_id
            set({ activeConvId: convId })

            if (meta.user_message_id) {
              set((s) => ({
                messages: s.messages.map((m) =>
                  m.id === userMsg.id ? { ...m, id: meta.user_message_id } : m,
                ),
              }))
            }
            if (meta.message_id) {
              set((s) => ({
                messages: s.messages.map((m) =>
                  m.id === assistantMsg.id ? { ...m, id: meta.message_id } : m,
                ),
              }))
            }

            set((s) => {
              const exists = s.conversations.some((c) => c.id === convId)
              if (exists) return {}
              return {
                conversations: [
                  { id: convId, title: body.conversation_title || query.slice(0, 100), updated_at: new Date().toISOString() },
                  ...s.conversations,
                ],
              }
            })
          },

          onDelta: (content) => {
            set((s) => {
              const msgs = [...s.messages]
              const last = msgs[msgs.length - 1]
              msgs[msgs.length - 1] = { ...last, content: last.content + content }
              return { messages: msgs }
            })
          },

          onDone: (payload) => {
            set((s) => {
              const msgs = [...s.messages]
              const last = msgs[msgs.length - 1]
              msgs[msgs.length - 1] = {
                ...last,
                isStreaming: false,
                sources: payload?.sources,
                citations: payload?.citations,
                latency_ms: payload?.latency_ms,
              }
              return { messages: msgs, isStreaming: false }
            })
            get().fetchConversations()
          },

          onError: (err) => {
            _updateLastMsg(set, {
              content: `Error: ${err.message}`,
              isStreaming: false,
              isError: true,
            })
            set({ isStreaming: false, error: err.message })
          },
        })

        if (activeStreamController === streamController) activeStreamController = null
      },
    }),
    { name: 'chat-store' },
  ),
)

// ---------- private helpers ----------

let _msgCounter = 0

function _makeMsg(role, content, extra = {}) {
  return { id: `tmp-${++_msgCounter}`, role, content, timestamp: new Date().toISOString(), ...extra }
}

function _updateLastMsg(set, patch) {
  set((s) => ({
    messages: s.messages.map((m, i) => (i === s.messages.length - 1 ? { ...m, ...patch } : m)),
  }))
}

function _cancelActiveStream(set) {
  if (!activeStreamController) return
  activeStreamController.abort()
  activeStreamController = null
  set((state) => ({
    isStreaming: false,
    messages: state.messages.map((message, index) => index === state.messages.length - 1 && message.isStreaming
      ? { ...message, content: message.content || 'Response stopped.', isStreaming: false, isCancelled: true }
      : message),
  }))
}
