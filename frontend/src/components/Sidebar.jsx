import {
  Bot,
  Plus,
  Home,
  LayoutGrid,
  Clock,
  HelpCircle,
  Settings,
  Shield,
  PanelLeftClose,
  PanelLeftOpen,
  X,
} from 'lucide-react'
import ConversationSearch from './ConversationSearch'
import ConversationHistory from './ConversationHistory'

function Sidebar({
  isCollapsed,
  onToggleCollapse,
  isMobileOpen,
  onCloseMobile,
  activeNav,
  onSelectNav,
  conversations,
  activeConversationId,
  searchQuery,
  isSearching,
  isLoadingHistory,
  onSearchChange,
  onClearSearch,
  onSelectConversation,
  onRequestRenameConversation,
  onRequestDeleteConversation,
  onNewChat,
  onOpenHelp,
  onOpenSettings,
  onOpenAdmin,
}) {
  const handleNavClick = (navKey) => {
    if (navKey === 'help') {
      onOpenHelp()
      onCloseMobile()
      return
    }
    if (navKey === 'recent' && isCollapsed) {
      onToggleCollapse()
    }
    onSelectNav(navKey)
    if (navKey === 'home' || navKey === 'overview') {
      onCloseMobile()
    }
  }

  return (
    <>
      {isMobileOpen && (
        <div
          className="sidebar-backdrop"
          onClick={onCloseMobile}
          aria-hidden="true"
        />
      )}

      <aside
        className={`sidebar ${isCollapsed ? 'sidebar-collapsed' : ''} ${
          isMobileOpen ? 'sidebar-mobile-open' : ''
        }`}
        aria-label="Sidebar navigation"
      >
        {/* Top Brand & Collapse Controls */}
        <div className="sidebar-header">
          <div
            className="brand-group"
            onClick={() => handleNavClick('home')}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleNavClick('home')
            }}
          >
            <div className="brand-logo" aria-hidden="true">
              <Bot size={20} strokeWidth={2.1} />
            </div>
            {!isCollapsed && (
              <div className="brand-text">
                <span className="brand-title">IntelliFAQ</span>
                <span className="brand-subtitle">AI Knowledge Workspace</span>
              </div>
            )}
          </div>

          <button
            type="button"
            className="sidebar-icon-btn desktop-only"
            onClick={onToggleCollapse}
            aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {isCollapsed ? (
              <PanelLeftOpen size={18} strokeWidth={2} />
            ) : (
              <PanelLeftClose size={18} strokeWidth={2} />
            )}
          </button>

          <button
            type="button"
            className="sidebar-icon-btn mobile-only"
            onClick={onCloseMobile}
            aria-label="Close navigation menu"
          >
            <X size={18} strokeWidth={2} />
          </button>
        </div>

        {/* New Chat Action */}
        <div className="sidebar-action-wrap">
          <button
            type="button"
            className="new-chat-btn"
            onClick={() => {
              onNewChat()
              onCloseMobile()
            }}
            title="Start a New Chat"
          >
            <Plus size={18} strokeWidth={2.2} />
            {!isCollapsed && <span>New Chat</span>}
          </button>
        </div>

        {/* Primary Navigation */}
        <nav className="sidebar-nav" aria-label="Primary">
          {!isCollapsed && (
            <div className="nav-section-label">Workspace</div>
          )}

          <button
            type="button"
            className={`nav-item ${
              activeNav === 'home' ? 'nav-item-active' : ''
            }`}
            onClick={() => handleNavClick('home')}
            title="Home Chat"
          >
            <Home size={17} strokeWidth={2} />
            {!isCollapsed && <span>Home</span>}
          </button>

          <button
            type="button"
            className={`nav-item ${
              activeNav === 'overview' ? 'nav-item-active' : ''
            }`}
            onClick={() => handleNavClick('overview')}
            title="Knowledge Base Overview"
          >
            <LayoutGrid size={17} strokeWidth={2} />
            {!isCollapsed && <span>Overview</span>}
          </button>

          <button
            type="button"
            className={`nav-item ${
              activeNav === 'recent' ? 'nav-item-active' : ''
            }`}
            onClick={() => handleNavClick('recent')}
            title="Recent Chats"
          >
            <Clock size={17} strokeWidth={2} />
            {!isCollapsed && (
              <>
                <span>Recent Chats</span>
                <span className="nav-badge">{conversations.length}</span>
              </>
            )}
          </button>

          <button
            type="button"
            className="nav-item"
            onClick={() => handleNavClick('help')}
            title="Help & FAQ Guide"
          >
            <HelpCircle size={17} strokeWidth={2} />
            {!isCollapsed && <span>Help</span>}
          </button>
        </nav>

        {/* Conversation History Section */}
        <div
          className={`sidebar-history ${
            activeNav === 'recent' ? 'sidebar-history-highlighted' : ''
          }`}
        >
          {!isCollapsed && (
            <>
              <div className="history-section-header">
                <span>Conversation History</span>
                {conversations.length > 0 && (
                  <span className="history-count-label">
                    {conversations.length}
                  </span>
                )}
              </div>

              <ConversationSearch
                value={searchQuery}
                onChange={onSearchChange}
                onClear={onClearSearch}
                isSearching={isSearching}
              />
            </>
          )}

          <ConversationHistory
            conversations={conversations}
            activeConversationId={activeConversationId}
            isCollapsed={isCollapsed}
            isLoading={isLoadingHistory}
            searchQuery={searchQuery}
            onSelectConversation={onSelectConversation}
            onRequestRename={onRequestRenameConversation}
            onRequestDelete={onRequestDeleteConversation}
            onCloseMobile={onCloseMobile}
          />
        </div>

        {/* Footer Settings & Admin Portal */}
        <div className="sidebar-footer">
          {onOpenAdmin && (
            <button
              type="button"
              className="nav-item"
              onClick={() => {
                onOpenAdmin()
                onCloseMobile()
              }}
              title="Open Admin Portal"
            >
              <Shield size={16} strokeWidth={2} />
              {!isCollapsed && <span>Admin Portal</span>}
            </button>
          )}
          <button
            type="button"
            className="settings-btn"
            onClick={() => {
              onOpenSettings()
              onCloseMobile()
            }}
            title="Preferences & Settings"
          >
            <div className="settings-icon-box">
              <Settings size={17} strokeWidth={2} />
            </div>
            {!isCollapsed && (
              <div className="settings-btn-text">
                <span className="settings-title">Settings</span>
                <span className="settings-sub">Display &amp; preferences</span>
              </div>
            )}
          </button>
        </div>
      </aside>
    </>
  )
}

export default Sidebar
