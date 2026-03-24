import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import { agentApi, streamChatCompletions } from '@/api/agent'
import { useAuthStore } from './authStore'

export const useChatStore = create(
  devtools(
    (set, get) => ({
      messages: [], // { id, role, content, timestamp, isLoading?, isStreaming?, isError? }
      isStreaming: false,
      error: null,
      // 'rag'  → POST /api/chat (RAG pipeline, structured answer)
      // 'stream' → POST /v1/chat/completions (OpenAI-compatible streaming)
      mode: 'rag',

      setMode: (mode) => set({ mode }),

      clearMessages: () => set({ messages: [], error: null }),

      // ---- RAG mode ----
      sendRagMessage: async (query) => {
        const { user } = useAuthStore.getState()
        const userMsg = _makeMsg('user', query)
        const assistantMsg = _makeMsg('assistant', '', { isLoading: true })

        set((s) => ({ messages: [...s.messages, userMsg, assistantMsg], isStreaming: true, error: null }))

        try {
          const { data } = await agentApi.chat({
            query,
            k: 5,
            user_id: user?.id,
            role: user?.roles?.includes('admin') ? 'admin' : 'user',
            tenant_id: user?.id,
          })

          const answer = data?.answer ?? data?.result ?? JSON.stringify(data)
          _updateLastMsg(set, { content: answer, isLoading: false })
        } catch (err) {
          _updateLastMsg(set, {
            content: `Error: ${err.response?.data?.detail ?? err.message ?? 'Request failed'}`,
            isLoading: false,
            isError: true,
          })
          set({ error: err.message })
        } finally {
          set({ isStreaming: false })
        }
      },

      // ---- Streaming mode (/v1/chat/completions) ----
      sendStreamMessage: async (content) => {
        const { messages } = get()
        const userMsg = _makeMsg('user', content)
        const assistantMsg = _makeMsg('assistant', '', { isStreaming: true })

        set((s) => ({
          messages: [...s.messages, userMsg, assistantMsg],
          isStreaming: true,
          error: null,
        }))

        // Build history including the new user message
        const history = [
          ...messages.map((m) => ({ role: m.role, content: m.content })),
          { role: 'user', content },
        ]

        await streamChatCompletions({
          messages: history,
          onChunk: (chunk) => {
            set((s) => ({
              messages: s.messages.map((m, i) =>
                i === s.messages.length - 1 ? { ...m, content: m.content + chunk } : m,
              ),
            }))
          },
          onDone: () => {
            _updateLastMsg(set, { isStreaming: false })
            set({ isStreaming: false })
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
      },
    }),
    { name: 'chat-store' },
  ),
)

// ---------- private helpers ----------

let _msgCounter = 0

function _makeMsg(role, content, extra = {}) {
  return { id: ++_msgCounter, role, content, timestamp: new Date().toISOString(), ...extra }
}

function _updateLastMsg(set, patch) {
  set((s) => ({
    messages: s.messages.map((m, i) => (i === s.messages.length - 1 ? { ...m, ...patch } : m)),
  }))
}
