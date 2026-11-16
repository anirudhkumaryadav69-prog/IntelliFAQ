import { useState, useRef } from 'react'
import { SendHorizontal, CornerDownLeft } from 'lucide-react'

function ChatInput({ onSendMessage, disabled }) {
  const [text, setText] = useState('')
  const textareaRef = useRef(null)

  const adjustHeight = (el) => {
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`
  }

  const handleChange = (e) => {
    setText(e.target.value)
    adjustHeight(e.target)
  }

  const submitMessage = () => {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSendMessage(trimmed)
    setText('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.focus()
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submitMessage()
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    submitMessage()
  }

  const isEmpty = text.trim().length === 0

  return (
    <div className="composer-container">
      <form className="composer-form" onSubmit={handleSubmit}>
        <div className="composer-input-wrapper">
          <textarea
            ref={textareaRef}
            rows={1}
            value={text}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question about admissions, fee payment, attendance, or exams..."
            className="composer-textarea"
            aria-label="Message input"
          />
          <button
            type="submit"
            className="composer-send-btn"
            disabled={isEmpty || disabled}
            aria-label="Send message"
            title="Send message (Enter)"
          >
            <SendHorizontal size={18} strokeWidth={2} />
          </button>
        </div>
        <div className="composer-footer">
          <span className="composer-hint">
            <CornerDownLeft size={12} strokeWidth={2} />
            Press <kbd>Enter</kbd> to send, <kbd>Shift + Enter</kbd> for newline
          </span>
          <span className="composer-disclaimer">
            IntelliFAQ uses NLP similarity matching to answer institutional FAQs
          </span>
        </div>
      </form>
    </div>
  )
}

export default ChatInput
