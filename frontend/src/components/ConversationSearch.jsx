import { Search, X } from 'lucide-react'

function ConversationSearch({
  value,
  onChange,
  onClear,
  isSearching = false,
}) {
  return (
    <div className="history-search-wrap">
      <div className="history-search-box">
        <Search size={14} strokeWidth={2} className="history-search-icon" aria-hidden="true" />
        <input
          type="text"
          className="history-search-input"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Search conversations..."
          aria-label="Search conversation history"
        />
        {isSearching && (
          <span className="history-search-spinner" aria-label="Searching" />
        )}
        {value && (
          <button
            type="button"
            className="history-search-clear"
            onClick={onClear}
            aria-label="Clear search"
            title="Clear search"
          >
            <X size={13} strokeWidth={2.2} />
          </button>
        )}
      </div>
    </div>
  )
}

export default ConversationSearch
