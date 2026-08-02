import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import { conversationsApi } from '@/api/conversations'
import { streamChat } from '@/api/agent'
import { useAuthStore } from './authStore'
import { useFeatureFlagStore } from './featureFlagStore'
import { toFailure } from '../lib/failures'

let activeStreamController = null
let requestedConversationId = null

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
      lastQuery: null,

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
            const references = _normalizeReferences(m.sources_used)
            return {
              id: m.id,
              role: m.role,
              content: m.status === 'error' ? _friendlyErrorMessage(new Error(m.error_message)) : m.content,
              timestamp: m.created_at,
              sources: references.map((reference) => reference.note_id),
              references,
              isError: m.status === 'error',
            }
          })
          const lastUserMessage = [...msgs].reverse().find((message) => message.role === 'user')
          set({ messages: msgs, lastQuery: lastUserMessage?.content ?? null, isLoadingMessages: false })
        } catch (err) {
          console.error('[chatStore] selectConversation failed:', err)
          set({ isLoadingMessages: false, error: 'Failed to load conversation' })
        }
      },

      newConversation: () => {
        _cancelActiveStream(set)
        set({ activeConvId: null, messages: [], lastQuery: null, error: null })
      },

      deleteConversation: async (convId) => {
        try {
          await conversationsApi.delete(convId)
          const { activeConvId } = get()
          if (requestedConversationId === convId) requestedConversationId = null
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
          lastQuery: query,
        }))

        const body = {
          query,
          k: 5,
          conversation_id: activeConvId || undefined,
          conversation_title: !activeConvId && messages.length === 0 ? query.slice(0, 100) : undefined,
        }

        const streamController = new AbortController()
        activeStreamController = streamController

        const useAgentWorkflow = useFeatureFlagStore.getState().isEnabled('chat.agent_workflow')

        await streamChat({
          body,
          endpoint: useAgentWorkflow ? '/api/chat/agent-stream' : '/api/chat/stream',
          signal: streamController.signal,
          onMeta: (meta) => {
            const convId = meta.conversation_id
            requestedConversationId = convId
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
                  m.id === assistantMsg.id ? {
                    ...m,
                    id: meta.message_id,
                    sources: meta.sources,
                    references: _normalizeReferences(meta.references ?? meta.sources),
                  } : m,
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
                sources: payload?.sources ?? last.sources,
                references: payload?.references || payload?.sources
                  ? _normalizeReferences(payload.references ?? payload.sources)
                  : last.references,
                latency_ms: payload?.latency_ms,
              }
              return { messages: msgs, isStreaming: false }
            })
            get().fetchConversations()
          },

          onError: (err) => {
            const failure = toFailure(err)
            console.error('[chatStore] sendMessage failed:', failure.code, err)
            _updateLastMsg(set, {
              content: failure.message,
              isStreaming: false,
              isError: true,
              // Kept so the UI can offer "try again" only when a retry could
              // work, and prompt a sign-in when the session is the problem.
              failureCode: failure.code,
              retryable: failure.retryable,
            })
            set({ isStreaming: false, error: failure.message, failureCode: failure.code })
          },
        })
        if (activeStreamController === streamController) activeStreamController = null
      },

      retryLastMessage: async () => {
        const { lastQuery, isStreaming } = get()
        if (!lastQuery || isStreaming) return
        await get().sendMessage(lastQuery)
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

/**
 * The server already decided what the user should read; this only unwraps it.
 *
 * It used to substring-match raw exception text to guess a message, which
 * meant any upstream rewording silently downgraded a precise failure to
 * "Something went wrong". Services now send {code, message, retryable} from
 * app/shared/failures.py.
 */
function _friendlyErrorMessage(err) {
  return toFailure(err).message
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

function _normalizeReferences(raw) {
  if (!Array.isArray(raw)) return []
  return raw
    .map((reference) => typeof reference === 'object'
      ? reference
      : { note_id: reference, title: 'Referenced note' })
    .filter((reference) => reference?.note_id)
}
