import { Bot } from 'lucide-react'

function TypingIndicator() {
  return (
    <div
      className="message-row message-row-assistant typing-row"
      role="status"
      aria-live="polite"
      aria-label="IntelliFAQ is typing a response"
    >
      <div className="message-avatar avatar-assistant" aria-hidden="true">
        <Bot size={18} strokeWidth={2} />
      </div>
      <div className="message-content-wrap">
        <div className="message-meta">
          <span className="message-sender">IntelliFAQ</span>
          <span className="typing-status-text">Matching FAQ knowledge base...</span>
        </div>
        <div className="message-bubble bubble-assistant typing-bubble">
          <span className="typing-dot" />
          <span className="typing-dot" />
          <span className="typing-dot" />
        </div>
      </div>
    </div>
  )
}

export default TypingIndicator
