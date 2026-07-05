import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { useAuthStore } from "@/stores/authStore";
import { useChatStore } from "@/stores/chatStore";
import { ArrowUp, Mic, Square } from "lucide-react";

const prompts = [
  ["Summarize", "Summarize the key ideas across my notes"],
  ["Connect ideas", "Find useful connections between my notes"],
  ["Plan", "Turn my recent notes into an action plan"],
];

export default function ChatPage() {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const conversations = useChatStore((s) => s.conversations);
  const activeConvId = useChatStore((s) => s.activeConvId);
  const messages = useChatStore((s) => s.messages);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const isLoadingMessages = useChatStore((s) => s.isLoadingMessages);
  const fetchConversations = useChatStore((s) => s.fetchConversations);
  const selectConversation = useChatStore((s) => s.selectConversation);
  const newConversation = useChatStore((s) => s.newConversation);
  const deleteConversation = useChatStore((s) => s.deleteConversation);
  const sendMessage = useChatStore((s) => s.sendMessage);
  const cancelStream = useChatStore((s) => s.cancelStream);
  const retryLastMessage = useChatStore((s) => s.retryLastMessage);

  const [input, setInput] = useState("");
  const [linkCopied, setLinkCopied] = useState(false);
  const bottomRef = useRef(null);
  const textareaRef = useRef(null);
  const activeConversation = conversations.find(
    (item) => String(item.id) === String(activeConvId),
  );

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  useEffect(() => {
    if (conversationId) selectConversation(conversationId);
    else newConversation();
  }, [conversationId, newConversation, selectConversation]);

  useEffect(() => {
    if (isStreaming && activeConvId && !conversationId)
      navigate(`/chat/${activeConvId}`, { replace: true });
  }, [activeConvId, conversationId, isStreaming, navigate]);

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      bottomRef.current?.scrollIntoView({
        behavior: isStreaming ? "auto" : "smooth",
      });
    });
    return () => cancelAnimationFrame(frame);
  }, [isStreaming, messages]);

  useEffect(() => () => cancelStream(), [cancelStream]);

  const handleSend = async (suggestion) => {
    const text = (suggestion ?? input).trim();
    if (!text || isStreaming) return;
    setInput("");
    await sendMessage(text);
    textareaRef.current?.focus();
  };

  const handleNewChat = () => {
    newConversation();
    setInput("");
    navigate("/chat");
    requestAnimationFrame(() => textareaRef.current?.focus());
  };

  const handleCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setLinkCopied(true);
      window.setTimeout(() => setLinkCopied(false), 1500);
    } catch {
      setLinkCopied(false);
    }
  };

  const handleDelete = async () => {
    if (!activeConvId || !window.confirm("Delete this conversation?")) return;
    await deleteConversation(activeConvId);
    navigate("/chat", { replace: true });
  };

  return (
    <div className="flex flex-col h-full min-w-0 overflow-hidden chat-workspace">
      <header className="workspace-border flex h-[74px] shrink-0 items-center justify-between border-b px-6 lg:px-8">
        <div className="min-w-0">
          <p className="workspace-faint text-xs font-semibold uppercase tracking-[0.15em]">
            Conversation
          </p>
          <h1 className="mt-1 text-sm font-medium truncate workspace-primary">
            {activeConversation?.title || "New conversation"}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handleNewChat} className="chat-new-button">
            <PlusIcon />
            New chat
          </button>
          <button onClick={handleCopyLink} className="chat-new-button">
            {linkCopied ? "Copied" : "Copy link"}
          </button>
          <button
            onClick={handleDelete}
            disabled={!activeConvId}
            className="chat-header-icon disabled:opacity-30"
            aria-label="Delete conversation"
            title="Delete conversation"
          >
            <TrashIcon />
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto workspace-scroll">
        {isLoadingMessages ? (
          <div className="flex items-center justify-center h-full">
            <span className="h-5 w-5 animate-spin rounded-full border-2 border-[#b8ff67]/20 border-t-[#b8ff67]" />
          </div>
        ) : messages.length === 0 ? (
          <EmptyState user={user} onPrompt={handleSend} />
        ) : (
          <div className="max-w-4xl px-5 pt-8 pb-32 mx-auto sm:px-8">
            {messages.map((message) => (
              <Message
                key={message.id}
                message={message}
                user={user}
                onRetry={retryLastMessage}
              />
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      <div className="absolute inset-x-0 bottom-0 z-10 px-4 pb-5 pointer-events-none chat-composer-fade pt-14 sm:px-7">
        <Composer
          input={input}
          setInput={setInput}
          textareaRef={textareaRef}
          isStreaming={isStreaming}
          onSend={() => handleSend()}
          onCancel={cancelStream}
          onPrompt={handleSend}
        />
      </div>
    </div>
  );
}

function EmptyState({ user, onPrompt }) {
  const firstName = user?.name?.split(" ")[0];
  return (
    <div className="flex flex-col items-center justify-center h-full max-w-3xl px-6 pb-24 mx-auto text-center">
      <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-[22px] border border-[#66a41f]/20 bg-[#66a41f]/10 text-2xl text-[#66a41f] shadow-[0_0_50px_rgba(184,255,103,0.08)]">
        ✦
      </div>
      <p className="text-xs font-medium uppercase tracking-[0.17em] text-[#66a41f]">
        Your knowledge workspace
      </p>
      <h2 className="workspace-primary mt-3 text-3xl font-medium tracking-[-0.035em] sm:text-4xl">
        What are we thinking about{firstName ? `, ${firstName}` : ""}?
      </h2>
      <p className="max-w-lg mt-3 text-sm leading-6 workspace-muted">
        Ask a question and NoteLite will find useful context across your notes
        before answering.
      </p>
      <div className="grid w-full gap-3 mt-9 sm:grid-cols-3">
        {prompts.map(([title, prompt]) => (
          <button
            key={title}
            onClick={() => onPrompt(prompt)}
            className="p-4 text-left workspace-card rounded-2xl"
          >
            <span className="block text-sm font-medium workspace-primary">
              {title}
            </span>
            <span className="workspace-muted mt-1.5 block text-xs font-light leading-5">
              {prompt}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function Message({ message, user, onRetry }) {
  const isUser = message.role === "user";
  const initials =
    user?.name?.[0]?.toUpperCase() ?? user?.email?.[0]?.toUpperCase() ?? "Y";
  const [copied, setCopied] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  if (isUser) {
    return (
      <div className="flex items-start justify-end gap-3 mb-8">
        <div className="workspace-card workspace-primary max-w-[78%] rounded-2xl rounded-tr-sm px-4 py-3 text-sm leading-6">
          {message.content}
        </div>
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#b8ff67] text-xs font-semibold text-[#10140d]">
          {initials}
        </span>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-3 mb-10">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-[#66a41f]/20 bg-[#66a41f]/10 text-xs text-[#66a41f]">
        ✦
      </span>
      <div
        className={`min-w-0 flex-1 pt-1 text-sm leading-7 ${message.isError ? "text-red-400" : "workspace-primary"}`}
      >
        {message.isStreaming && !message.content ? (
          <span className="flex items-center h-6 gap-1">
            {[0, 150, 300].map((delay) => (
              <span
                key={delay}
                className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#b8ff67]"
                style={{ animationDelay: `${delay}ms` }}
              />
            ))}
          </span>
        ) : (
          <div className="chat-markdown">
            <ReactMarkdown>{message.content}</ReactMarkdown>
          </div>
        )}
        {message.isStreaming && message.content && (
          <span className="animate-pulse text-[#b8ff67]">▋</span>
        )}
        {!message.isStreaming && (
          <div className="flex flex-wrap items-center gap-2 mt-3 text-xs workspace-faint">
            {!message.isError && (
              <button
                onClick={handleCopy}
                className="workspace-pill rounded-full px-2.5 py-1"
              >
                {copied ? "Copied" : "Copy"}
              </button>
            )}
            {!message.isError && message.references?.length > 0 && (
              <button
                onClick={() => setSourcesOpen((open) => !open)}
                className="workspace-pill rounded-full px-2.5 py-1"
              >
                {message.references.length}{" "}
                {message.references.length === 1 ? "source" : "sources"} ·
                chunks
              </button>
            )}
            {message.isError && (
              <button
                onClick={onRetry}
                className="workspace-pill rounded-full px-2.5 py-1"
              >
                Retry
              </button>
            )}
            <time title={formatTimestamp(message.timestamp)}>
              {shortTimestamp(message.timestamp)}
            </time>
          </div>
        )}
        {sourcesOpen && <SourceDebugPanel references={message.references} />}
      </div>
    </div>
  );
}

function SourceDebugPanel({ references }) {
  return (
    <aside className="source-debug-panel">
      <div className="source-debug-heading">
        <span>Retrieval evidence</span>
        <span>
          {references.reduce(
            (count, reference) => count + (reference.chunks?.length ?? 0),
            0,
          )}{" "}
          context chunks
        </span>
      </div>
      {references.map((reference) => (
        <details key={reference.note_id} className="source-debug-note">
          <summary>
            <span className="flex-1 min-w-0">
              <strong>{reference.title || "Untitled note"}</strong>
              <small>
                {reference.folder ? `${reference.folder} · ` : ""}
                {reference.chunks?.length ??
                  reference.chunk_ids?.length ??
                  0}{" "}
                chunks
              </small>
            </span>
            <button
              type="button"
              onClick={(event) => {
                event.preventDefault();
                window.open(
                  reference.folder_id
                    ? `/folders/${reference.folder_id}?note=${reference.note_id}`
                    : `/notes?note=${reference.note_id}`,
                  "_blank",
                  "noopener,noreferrer",
                );
              }}
            >
              Open note
            </button>
          </summary>
          <div className="source-debug-chunks">
            {reference.chunks?.length ? (
              reference.chunks.map((chunk) => (
                <ChunkDebugCard key={chunk.chunk_id} chunk={chunk} />
              ))
            ) : (
              <p className="source-debug-legacy">
                Exact chunk text was not stored for this older response. Chunk
                IDs: {(reference.chunk_ids ?? []).join(", ") || "unavailable"}.
              </p>
            )}
          </div>
        </details>
      ))}
    </aside>
  );
}

function ChunkDebugCard({ chunk }) {
  const position = Number.isInteger(chunk.chunk_index)
    ? `${chunk.chunk_index + 1}${chunk.total_chunks ? ` / ${chunk.total_chunks}` : ""}`
    : "unknown";
  return (
    <article className="source-debug-chunk">
      <div className="source-debug-meta">
        <span>{chunk.is_seed ? "Selected chunk" : "Neighbor context"}</span>
        <span>Position {position}</span>
        {chunk.chunk_type && <span>{chunk.chunk_type}</span>}
        {typeof chunk.score === "number" && (
          <span>Score {chunk.score.toFixed(4)}</span>
        )}
        <code>{chunk.chunk_id}</code>
      </div>
      <pre>{chunk.text}</pre>
    </article>
  );
}

function Composer({
  input,
  setInput,
  textareaRef,
  isStreaming,
  onSend,
  onCancel,
  onPrompt,
}) {
  const handleKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();

      if (!isStreaming && input.trim()) {
        onSend();
      }
    }
  };

  const handleInput = (event) => {
    setInput(event.target.value);

    const el = event.target;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  return (
    <div className="chat-composer pointer-events-auto mx-auto flex w-full max-w-4xl items-end gap-2 rounded-[24px] bg-white p-3 shadow-2xl">
      <textarea
        ref={textareaRef}
        value={input}
        onChange={handleInput}
        onKeyDown={handleKeyDown}
        rows={1}
        placeholder="Ask anything about your notes..."
        className="
      max-h-40 min-h-[44px] flex-1 resize-none overflow-y-auto
      bg-transparent px-2 py-2 text-sm leading-6
      text-zinc-900 outline-none
      placeholder:text-zinc-500
    "
      />

      <div className="flex h-[44px] items-center gap-1">
        <button
          type="button"
          onClick={onPrompt}
          className="flex items-center justify-center transition h-9 w-9 text-zinc-500 hover:text-zinc-900"
          aria-label="Voice input"
        >
          <Mic className="w-4 h-4" />
        </button>

        <button
          type="button"
          onClick={isStreaming ? onCancel : onSend}
          disabled={!isStreaming && !input.trim()}
          className={`
  flex h-9 w-9 items-center justify-center rounded-full
  transition-all duration-200
  ${
    isStreaming
      ? "bg-red-500 text-white hover:bg-red-600"
      : "text-zinc-500 hover:text-green-800 hover:border-green-800"
  }
  disabled:opacity-50
  disabled:cursor-not-allowed
`}
          aria-label={isStreaming ? "Stop response" : "Send message"}
        >
          {isStreaming ? (
            <Square className="h-3.5 w-3.5 text-current" />
          ) : (
            <ArrowUp className="w-5 h-5" strokeWidth={2} />
          )}
        </button>
      </div>
    </div>
  );
}

function PlusIcon() {
  return (
    <svg
      className="h-3.5 w-3.5"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 5v14m7-7H5" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg
      className="h-3.5 w-3.5"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M19 7l-.9 12.1a2 2 0 01-2 1.9H7.9a2 2 0 01-2-1.9L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
      />
    </svg>
  );
}

function shortTimestamp(timestamp) {
  if (!timestamp) return "";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function formatTimestamp(timestamp) {
  if (!timestamp) return "";
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}
