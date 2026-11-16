import { MessageSquare } from 'lucide-react'
import ConversationMenu from './ConversationMenu'

const SECTION_ORDER = ['Today', 'Yesterday', 'Previous 7 Days', 'Older']

function getDateBucket(isoString) {
  if (!isoString) return 'Older'
  const date = new Date(isoString)
  if (Number.isNaN(date.getTime())) return 'Older'

  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const startOfDate = new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate()
  )
  const diffDays = Math.round(
    (startOfToday.getTime() - startOfDate.getTime()) / (1000 * 60 * 60 * 24)
  )

  if (diffDays <= 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  if (diffDays <= 7) return 'Previous 7 Days'
  return 'Older'
}

function formatConversationTime(isoString) {
  if (!isoString) return 'Just now'
  const date = new Date(isoString)
  if (Number.isNaN(date.getTime())) return String(isoString)

  const bucket = getDateBucket(isoString)
  if (bucket === 'Today') {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

function ConversationHistory({
  conversations,
  activeConversationId,
  isCollapsed,
  isLoading,
  searchQuery,
  onSelectConversation,
  onRequestRename,
  onRequestDelete,
  onCloseMobile,
}) {
  if (isLoading && conversations.length === 0) {
    return !isCollapsed ? (
      <div className="history-empty">
        <p>Loading conversations...</p>
      </div>
    ) : null
  }

  if (conversations.length === 0) {
    if (isCollapsed) return null
    const hasSearch = Boolean(searchQuery && searchQuery.trim())
    return (
      <div className="history-empty">
        <p>{hasSearch ? 'No matching conversations' : 'No saved conversations yet'}</p>
        <span>
          {hasSearch
            ? 'Try a different keyword or clear the search'
            : 'Ask a question to start a session'}
        </span>
      </div>
    )
  }

  const grouped = {
    Today: [],
    Yesterday: [],
    'Previous 7 Days': [],
    Older: [],
  }
  for (const conv of conversations) {
    const bucket = getDateBucket(conv.updatedAtIso || conv.updated_at)
    grouped[bucket].push(conv)
  }

  return (
    <div className="history-list" role="list">
      {SECTION_ORDER.map((sectionName) => {
        const items = grouped[sectionName]
        if (!items || items.length === 0) return null

        return (
          <div key={sectionName} className="history-group">
            {!isCollapsed && (
              <div className="history-group-label">{sectionName}</div>
            )}
            {items.map((conv) => {
              const isActive =
                conv.id === activeConversationId ||
                (conv.conversationId &&
                  conv.conversationId === activeConversationId)
              const msgCount =
                typeof conv.messageCount === 'number'
                  ? conv.messageCount
                  : Array.isArray(conv.messages)
                  ? conv.messages.length
                  : 0
              const timeLabel = formatConversationTime(
                conv.updatedAtIso || conv.updated_at
              )

              return (
                <div
                  key={conv.id}
                  role="listitem"
                  className={`history-item ${
                    isActive ? 'history-item-active' : ''
                  }`}
                >
                  <button
                    type="button"
                    className="history-select-btn"
                    onClick={() => {
                      onSelectConversation(conv.id)
                      onCloseMobile()
                    }}
                    title={conv.title}
                  >
                    <MessageSquare
                      size={15}
                      strokeWidth={2}
                      className="history-icon"
                    />
                    {!isCollapsed && (
                      <div className="history-info">
                        <span className="history-title">{conv.title}</span>
                        <span className="history-time">
                          {timeLabel}
                          {msgCount > 0 ? ` • ${msgCount} msgs` : ''}
                          {conv.lastCategory ? ` • ${conv.lastCategory}` : ''}
                        </span>
                      </div>
                    )}
                  </button>

                  {!isCollapsed && (
                    <ConversationMenu
                      conversation={conv}
                      onRename={onRequestRename}
                      onDelete={onRequestDelete}
                    />
                  )}
                </div>
              )
            })}
          </div>
        )
      })}
    </div>
  )
}

export default ConversationHistory
