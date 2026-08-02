import { useRef } from 'react'

export default function ChatComposer({ input, isStreaming, onInputChange, onSend, onCancel }) {
  const textareaRef = useRef(null)

  const handleKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      onSend()
    }
  }

  const handleSend = () => {
    onSend()
    textareaRef.current?.focus()
  }

  return (
    <footer className="chat-composer">
      <div className="flex items-end gap-3">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(event) => onInputChange(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask a question... (Enter to send | Shift+Enter for newline)"
          rows={1}
          className="chat-composer-input"
        />
        {isStreaming ? (
          <button type="button" onClick={onCancel} className="chat-stop-button">Stop</button>
        ) : (
          <button type="button" onClick={handleSend} disabled={!input.trim()} className="chat-send-button">
            Send
          </button>
        )}
      </div>
    </footer>
  )
}
