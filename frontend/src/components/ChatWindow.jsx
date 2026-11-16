import { useEffect, useRef } from 'react'
import {
  Menu,
  Bot,
  Sparkles,
  RotateCcw,
  HelpCircle,
  Database,
  Layers,
  Activity,
  MessageSquare,
  ArrowUpRight,
  RefreshCw,
  Tag,
  AlertCircle,
  CheckCircle2,
  X,
} from 'lucide-react'
import SuggestedQuestions from './SuggestedQuestions'
import MessageBubble from './MessageBubble'
import TypingIndicator from './TypingIndicator'
import ChatInput from './ChatInput'

function ChatWindow({
  messages,
  isTyping,
  onSendMessage,
  onNewChat,
  onResetChat,
  onOpenMobileSidebar,
  onOpenHelp,
  preferences,
  backendHealth,
  onRecheckHealth,
  activeNav,
  onSelectNav,
  faqDirectory,
  sessionQuestionsCount,
  activeBackendConversationId,
  activeTopicCategory,
  statusBanner,
  onDismissBanner,
}) {
  const messagesEndRef = useRef(null)

  useEffect(() => {
    if (activeNav !== 'overview' && preferences?.autoScroll !== false) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, isTyping, preferences?.autoScroll, activeNav])

  const hasMessages = messages.length > 0
  const isConnected = Boolean(backendHealth?.connected)
  const faqCount =
    faqDirectory?.totalCount || backendHealth?.faqCount || 0
  const categories = faqDirectory?.categories || []
  const categoryDistribution = faqDirectory?.distribution || []
  const isOverview = activeNav === 'overview'

  const handleResetClick = () => {
    if (typeof onResetChat === 'function') {
      onResetChat()
    } else if (typeof onNewChat === 'function') {
      onNewChat()
    }
  }

  return (
    <main className="chat-window" aria-label="Chat workspace">
      {/* Top Chat Header */}
      <header className="chat-header">
        <div className="chat-header-left">
          <button
            type="button"
            className="mobile-menu-btn"
            onClick={onOpenMobileSidebar}
            aria-label="Open navigation menu"
          >
            <Menu size={20} strokeWidth={2} />
          </button>

          <div className="header-bot-identity">
            <div className="header-bot-avatar" aria-hidden="true">
              <Bot size={20} strokeWidth={2} />
              <span
                className={`status-dot-ring ${
                  !isConnected ? 'status-dot-offline' : ''
                }`}
              />
            </div>
            <div className="header-bot-details">
              <div className="header-title-row">
                <h1 className="header-title">IntelliFAQ</h1>
                <button
                  type="button"
                  className={`status-pill ${
                    isConnected
                      ? 'status-pill-connected'
                      : 'status-pill-disconnected'
                  }`}
                  onClick={onRecheckHealth}
                  title={
                    isConnected
                      ? `Connected to Flask NLP Server (${faqCount} FAQs loaded)`
                      : 'Disconnected from backend — Click to retry health check'
                  }
                >
                  <span
                    className={`status-indicator ${
                      !isConnected ? 'status-indicator-offline' : ''
                    }`}
                  />
                  <span>{isConnected ? 'Connected' : 'Disconnected'}</span>
                  {isConnected && faqCount > 0 && (
                    <span className="status-pill-count">• {faqCount} FAQs</span>
                  )}
                </button>

                {!isOverview && activeTopicCategory && (
                  <span
                    className="header-context-pill"
                    title="Active conversation topic context tracked by IntelliFAQ"
                  >
                    <Tag size={11} strokeWidth={2} />
                    <span>Context: {activeTopicCategory}</span>
                  </span>
                )}
              </div>
              <p className="header-subtitle">
                NLP-Powered Institutional FAQ &amp; Context-Aware Knowledge Assistant
              </p>
            </div>
          </div>
        </div>

        <div className="chat-header-actions">
          <div className="header-view-segmented" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={!isOverview}
              className={`segmented-btn ${
                !isOverview ? 'segmented-btn-active' : ''
              }`}
              onClick={() => onSelectNav('home')}
            >
              Chat
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={isOverview}
              className={`segmented-btn ${
                isOverview ? 'segmented-btn-active' : ''
              }`}
              onClick={() => onSelectNav('overview')}
            >
              Overview
            </button>
          </div>

          {hasMessages && !isOverview && (
            <button
              type="button"
              className="header-action-btn"
              onClick={handleResetClick}
              disabled={isTyping}
              title="Reset server-side conversation context and clear current chat"
            >
              <RotateCcw size={14} strokeWidth={2} />
              <span>Reset Chat</span>
            </button>
          )}

          <button
            type="button"
            className="header-icon-btn"
            onClick={onOpenHelp}
            aria-label="Open Help Guide"
            title="Help & Supported Topics"
          >
            <HelpCircle size={18} strokeWidth={2} />
          </button>
        </div>
      </header>

      {/* Optional Status / Reset Error Notification Banner */}
      {statusBanner && (
        <div
          className={`workspace-status-banner ${
            statusBanner.type === 'error'
              ? 'workspace-banner-error'
              : 'workspace-banner-info'
          }`}
          role="status"
          aria-live="polite"
        >
          <div className="workspace-banner-content">
            {statusBanner.type === 'error' ? (
              <AlertCircle size={15} strokeWidth={2} />
            ) : (
              <CheckCircle2 size={15} strokeWidth={2} />
            )}
            <span>{statusBanner.message}</span>
          </div>
          {onDismissBanner && (
            <button
              type="button"
              className="workspace-banner-close"
              onClick={onDismissBanner}
              aria-label="Dismiss notification"
            >
              <X size={14} strokeWidth={2} />
            </button>
          )}
        </div>
      )}

      {/* Scrollable Main Viewport */}
      <div
        className={`chat-viewport ${
          preferences?.compactMode ? 'chat-viewport-compact' : ''
        }`}
      >
        {isOverview ? (
          <section
            className="overview-container"
            aria-label="Knowledge Base Overview"
          >
            <div className="overview-header-card">
              <div>
                <div className="welcome-badge">
                  <Sparkles size={13} strokeWidth={2} />
                  <span>Live NLP Knowledge Telemetry</span>
                </div>
                <h2 className="overview-title">Knowledge Base Overview</h2>
                <p className="overview-subtitle">
                  Real-time dataset metrics loaded directly from the Flask
                  TF-IDF &amp; Cosine Similarity backend.
                </p>
              </div>
              <button
                type="button"
                className="header-action-btn"
                onClick={onRecheckHealth}
                title="Refresh backend metrics"
              >
                <RefreshCw size={14} strokeWidth={2} />
                <span>Refresh Status</span>
              </button>
            </div>

            {/* 4 Key Metric Cards */}
            <div className="overview-stats-grid">
              <div className="overview-stat-card">
                <div className="stat-icon-wrap">
                  <Database size={18} strokeWidth={2} />
                </div>
                <div className="stat-details">
                  <span className="stat-label">Total FAQs Loaded</span>
                  <span className="stat-value">{faqCount}</span>
                  <span className="stat-meta">From backend/data/faqs.json</span>
                </div>
              </div>

              <div className="overview-stat-card">
                <div className="stat-icon-wrap">
                  <Layers size={18} strokeWidth={2} />
                </div>
                <div className="stat-details">
                  <span className="stat-label">FAQ Categories</span>
                  <span className="stat-value">{categories.length}</span>
                  <span className="stat-meta">Institutional domains</span>
                </div>
              </div>

              <div className="overview-stat-card">
                <div
                  className={`stat-icon-wrap ${
                    isConnected ? 'stat-icon-online' : 'stat-icon-offline'
                  }`}
                >
                  <Activity size={18} strokeWidth={2} />
                </div>
                <div className="stat-details">
                  <span className="stat-label">Backend Status</span>
                  <span className="stat-value">
                    {isConnected ? 'Connected' : 'Disconnected'}
                  </span>
                  <span className="stat-meta">
                    Engine: {backendHealth?.chatbotStatus || 'unavailable'}
                  </span>
                </div>
              </div>

              <div className="overview-stat-card">
                <div className="stat-icon-wrap">
                  <MessageSquare size={18} strokeWidth={2} />
                </div>
                <div className="stat-details">
                  <span className="stat-label">Session Questions</span>
                  <span className="stat-value">{sessionQuestionsCount}</span>
                  <span className="stat-meta">Asked during this session</span>
                </div>
              </div>
            </div>

            {/* Category Distribution Table / Bars */}
            <div className="overview-distribution-card">
              <div className="distribution-header">
                <div>
                  <h3 className="distribution-title">
                    Category Distribution
                  </h3>
                  <p className="distribution-desc">
                    Actual FAQ breakdown across institutional categories. Click
                    any sample question to test it in chat.
                  </p>
                </div>
              </div>

              {categoryDistribution.length === 0 ? (
                <div className="distribution-empty">
                  {isConnected
                    ? 'Loading FAQ category distribution...'
                    : 'Unable to load FAQ distribution while disconnected from the backend.'}
                </div>
              ) : (
                <div className="distribution-list">
                  {categoryDistribution.map((item) => {
                    const percentage =
                      faqCount > 0
                        ? Math.round((item.count / faqCount) * 100)
                        : 0
                    return (
                      <div key={item.category} className="distribution-row">
                        <div className="distribution-row-top">
                          <div className="distribution-cat-info">
                            <span className="distribution-cat-name">
                              {item.category}
                            </span>
                            <span className="distribution-cat-count">
                              {item.count} FAQs ({percentage}%)
                            </span>
                          </div>
                          {item.sampleQuestion && (
                            <button
                              type="button"
                              className="distribution-ask-btn"
                              onClick={() => onSendMessage(item.sampleQuestion)}
                              disabled={isTyping}
                              title={`Ask: "${item.sampleQuestion}"`}
                            >
                              <span>Ask sample</span>
                              <ArrowUpRight size={13} />
                            </button>
                          )}
                        </div>
                        <div className="distribution-bar-track">
                          <div
                            className="distribution-bar-fill"
                            style={{ width: `${percentage}%` }}
                          />
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </section>
        ) : !hasMessages ? (
          <section className="welcome-container" aria-label="Welcome screen">
            <div className="welcome-hero-card">
              <div className="welcome-badge">
                <Sparkles size={14} strokeWidth={2} />
                <span>Intelligent Multi-Turn FAQ Assistant</span>
              </div>

              <h2 className="welcome-heading">How can I help you today?</h2>

              <p className="welcome-intro">
                Welcome to <strong>IntelliFAQ</strong>. Ask any question about
                admissions, tuition fee payments, academic attendance policies,
                scholarships, campus facilities, or examination schedules—and
                follow up naturally within the same conversation.
              </p>

              <SuggestedQuestions
                onSelectQuestion={onSendMessage}
                disabled={isTyping}
              />
            </div>
          </section>
        ) : (
          <div className="messages-stream" role="log" aria-live="polite">
            <div className="session-divider">
              <span>
                {activeBackendConversationId
                  ? `Context-Aware Session • ID ${activeBackendConversationId.slice(0, 8)}`
                  : 'IntelliFAQ Session Started'}
              </span>
              {activeTopicCategory && (
                <span className="session-topic-pill">
                  <Tag size={10} strokeWidth={2} />
                  {activeTopicCategory}
                </span>
              )}
            </div>

            {messages.map((msg) => (
              <MessageBubble
                key={msg.id}
                message={msg}
                showTimestamps={preferences?.showTimestamps ?? true}
                onSelectQuestion={onSendMessage}
                disabled={isTyping}
              />
            ))}

            {isTyping && <TypingIndicator />}

            <div ref={messagesEndRef} className="scroll-anchor" />
          </div>
        )}
      </div>

      {/* Bottom Message Composer */}
      <ChatInput onSendMessage={onSendMessage} disabled={isTyping} />
    </main>
  )
}

export default ChatWindow
