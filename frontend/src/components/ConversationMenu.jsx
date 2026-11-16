import { useState, useEffect, useRef } from 'react'
import { MoreVertical, Pencil, Trash2 } from 'lucide-react'

function ConversationMenu({ conversation, onRename, onDelete }) {
  const [isOpen, setIsOpen] = useState(false)
  const menuRef = useRef(null)

  useEffect(() => {
    if (!isOpen) return
    const handleOutsideClick = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setIsOpen(false)
      }
    }
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleOutsideClick)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen])

  return (
    <div className="history-menu-wrap" ref={menuRef}>
      <button
        type="button"
        className="history-menu-trigger"
        onClick={(e) => {
          e.stopPropagation()
          setIsOpen((prev) => !prev)
        }}
        aria-label={`Actions for ${conversation.title}`}
        aria-expanded={isOpen}
        title="Conversation actions"
      >
        <MoreVertical size={14} strokeWidth={2} />
      </button>

      {isOpen && (
        <div
          className="history-context-menu"
          role="menu"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            role="menuitem"
            className="history-menu-item"
            onClick={() => {
              setIsOpen(false)
              onRename(conversation)
            }}
          >
            <Pencil size={13} strokeWidth={2} />
            <span>Rename</span>
          </button>
          <button
            type="button"
            role="menuitem"
            className="history-menu-item history-menu-item-danger"
            onClick={() => {
              setIsOpen(false)
              onDelete(conversation)
            }}
          >
            <Trash2 size={13} strokeWidth={2} />
            <span>Delete</span>
          </button>
        </div>
      )}
    </div>
  )
}

export default ConversationMenu
