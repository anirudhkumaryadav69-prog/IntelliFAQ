import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import {
  X,
  BookOpen,
  Sliders,
  Trash2,
  CheckCircle2,
  Sparkles,
} from 'lucide-react'
import Sidebar from './components/Sidebar'
import ChatWindow from './components/ChatWindow'
import RenameConversationDialog from './components/RenameConversationDialog'
import DeleteConversationDialog from './components/DeleteConversationDialog'
import AdminLayout from './components/admin/AdminLayout'
import {
  checkBackendHealth,
  fetchFaqDirectory,
  sendChatMessage,
  resetConversation,
  fetchConversations,
  searchConversations,
  fetchConversationDetail,
  renameConversation,
  deleteConversationById,
} from './services/api'
import './App.css'

function formatCurrentTime() {
  return new Date().toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatIsoTime(isoString) {
  if (!isoString) return formatCurrentTime()
  const d = new Date(isoString)
  if (Number.isNaN(d.getTime())) return formatCurrentTime()
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function mapSummaryToUiConversation(item, existing = null) {
  return {
    id: item.conversation_id,
    conversationId: item.conversation_id,
    title: item.title || 'New Conversation',
    isTitleCustom: Boolean(item.is_title_custom),
    updatedAtIso: item.updated_at || new Date().toISOString(),
    updatedAt: formatIsoTime(item.updated_at),
    lastCategory: item.last_category ?? existing?.lastCategory ?? null,
    lastFaqId: item.last_faq_id ?? existing?.lastFaqId ?? null,
    messageCount:
      typeof item.message_count === 'number'
        ? item.message_count
        : existing?.messageCount ?? 0,
    hasActiveClarification: Boolean(item.has_active_clarification),
    messages: existing?.messages ?? null,
  }
}

function mapStoredMessageToUiMessage(msg) {
  if (msg.role === 'user') {
    return {
      id: `db-user-${msg.message_id}`,
      sender: 'user',
      text: msg.message_text || '',
      timestamp: formatIsoTime(msg.created_at),
    }
  }
  return {
    id: `db-bot-${msg.message_id}`,
    sender: 'assistant',
    text: msg.message_text || '',
    matchedQuestion: msg.matched_question ?? null,
    category: msg.category ?? null,
    confidence: typeof msg.confidence === 'number' ? msg.confidence : 0,
    faqId: msg.faq_id ?? null,
    fallback: Boolean(msg.fallback),
    matchType: msg.match_type || 'clear_match',
    candidates: Array.isArray(msg.candidates) ? msg.candidates : [],
    needsClarification: Boolean(msg.needs_clarification),
    clarificationMessage: msg.clarification_message ?? null,
    isMultiIntent: Boolean(msg.is_multi_intent),
    subResponses: Array.isArray(msg.sub_responses) ? msg.sub_responses : [],
    followUpSuggestions: [],
    success: true,
    isConnectionError: false,
    timestamp: formatIsoTime(msg.created_at),
  }
}

/**
 * Extract lowercase alphanumeric content words (length > 2) for lightweight
 * lexical overlap ranking of same-category follow-up FAQs.
 */
function extractKeywords(text) {
  if (typeof text !== 'string') return new Set()
  const stopWords = new Set([
    'what',
    'where',
    'when',
    'which',
    'who',
    'whom',
    'whose',
    'why',
    'how',
    'are',
    'can',
    'the',
    'for',
    'and',
    'with',
    'from',
    'that',
    'this',
    'have',
    'has',
    'does',
    'there',
    'any',
  ])
  const words = text.toLowerCase().match(/\b[a-z0-9]{3,}\b/g) || []
  return new Set(words.filter((w) => !stopWords.has(w)))
}

/**
 * Dynamically select 2–3 relevant follow-up FAQ suggestions from the loaded
 * GET /api/faqs dataset after a `clear_match` response.
 *
 * Rules:
 * - Only returns suggestions for `clear_match` responses (never for ambiguous
 *   or fallback responses).
 * - Prefers FAQs in the exact same category.
 * - Excludes the currently answered FAQ and any FAQs already answered in the
 *   current conversation.
 * - Prevents duplicate suggestions.
 */
function computeSmartFollowUps({
  matchType,
  fallback,
  needsClarification,
  faqId,
  category,
  matchedQuestion,
  candidates = [],
  allFaqs = [],
  answeredFaqIds = new Set(),
  maxSuggestions = 3,
}) {
  if (
    matchType !== 'clear_match' ||
    fallback ||
    needsClarification ||
    faqId == null ||
    !category ||
    !Array.isArray(allFaqs) ||
    allFaqs.length === 0
  ) {
    return []
  }

  const excludedIds = new Set(answeredFaqIds)
  excludedIds.add(faqId)

  const seenQuestions = new Set()
  if (typeof matchedQuestion === 'string' && matchedQuestion.trim()) {
    seenQuestions.add(matchedQuestion.trim().toLowerCase())
  }

  const results = []
  const faqById = new Map(allFaqs.map((f) => [f.id, f]))

  // 1. First check backend-ranked candidates that belong to the SAME category
  //    and have meaningful similarity (>= 15%).
  if (Array.isArray(candidates)) {
    for (const cand of candidates) {
      if (results.length >= maxSuggestions) break
      if (
        !cand ||
        cand.category !== category ||
        cand.faq_id == null ||
        excludedIds.has(cand.faq_id) ||
        (typeof cand.similarity === 'number' && cand.similarity < 15)
      ) {
        continue
      }

      const directoryFaq = faqById.get(cand.faq_id)
      const canonicalQuestion = directoryFaq?.question || cand.question
      if (!canonicalQuestion) continue

      const normalizedQ = canonicalQuestion.trim().toLowerCase()
      if (seenQuestions.has(normalizedQ)) continue

      seenQuestions.add(normalizedQ)
      excludedIds.add(cand.faq_id)
      results.push({
        id: cand.faq_id,
        question: canonicalQuestion.trim(),
        category,
      })
    }
  }

  if (results.length >= maxSuggestions) {
    return results
  }

  // 2. Fill remaining slots (up to 3 total) from same-category FAQs in the
  //    GET /api/faqs directory, ranked by keyword overlap and workflow proximity.
  const matchedKeywords = extractKeywords(matchedQuestion || '')

  const sameCategoryPool = allFaqs
    .filter((item) => {
      if (!item || item.category !== category) return false
      if (excludedIds.has(item.id)) return false
      const normQ = (item.question || '').trim().toLowerCase()
      return Boolean(normQ) && !seenQuestions.has(normQ)
    })
    .map((item) => {
      const itemKeywords = extractKeywords(item.question)
      let sharedCount = 0
      for (const kw of itemKeywords) {
        if (matchedKeywords.has(kw)) sharedCount += 1
      }
      const idDistance =
        typeof item.id === 'number' && typeof faqId === 'number'
          ? Math.abs(item.id - faqId)
          : 999
      return {
        item,
        sharedCount,
        idDistance,
      }
    })
    .sort((a, b) => {
      if (b.sharedCount !== a.sharedCount) {
        return b.sharedCount - a.sharedCount
      }
      return a.idDistance - b.idDistance
    })

  for (const entry of sameCategoryPool) {
    if (results.length >= maxSuggestions) break
    const { item } = entry
    const normQ = item.question.trim().toLowerCase()
    if (seenQuestions.has(normQ)) continue
    seenQuestions.add(normQ)
    excludedIds.add(item.id)
    results.push({
      id: item.id,
      question: item.question.trim(),
      category: item.category,
    })
  }

  return results
}

function App() {
  const [currentPath, setCurrentPath] = useState(
    () => window.location.pathname || '/'
  )

  useEffect(() => {
    const onPopState = () => {
      setCurrentPath(window.location.pathname || '/')
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const navigate = useCallback((path) => {
    if (window.location.pathname !== path) {
      window.history.pushState({}, '', path)
    }
    setCurrentPath(path)
  }, [])

  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false)
  const [activeNav, setActiveNav] = useState('home')

  const [conversations, setConversations] = useState([])
  const [activeConversationId, setActiveConversationId] = useState(null)
  const [messages, setMessages] = useState([])
  const [isTyping, setIsTyping] = useState(false)
  const [sessionQuestionsCount, setSessionQuestionsCount] = useState(0)
  const [statusBanner, setStatusBanner] = useState(null)

  const [backendHealth, setBackendHealth] = useState({
    connected: false,
    chatbotStatus: 'checking',
    faqCount: 0,
    message: 'Checking connection...',
  })

  const [faqDirectory, setFaqDirectory] = useState({
    totalCount: 0,
    categories: [],
    faqs: [],
    distribution: [],
  })

  const [isHelpOpen, setIsHelpOpen] = useState(false)
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [isSearching, setIsSearching] = useState(false)
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const [renameTarget, setRenameTarget] = useState(null)
  const [isRenaming, setIsRenaming] = useState(false)
  const [renameError, setRenameError] = useState('')
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const [preferences, setPreferences] = useState({
    showTimestamps: true,
    autoScroll: true,
    compactMode: false,
  })

  // Track active request generation so switching/resetting chat ignores stale responses
  const activeRequestIdRef = useRef(0)
  const searchRequestIdRef = useRef(0)

  const refreshConversations = useCallback(async (query = '') => {
    const reqId = searchRequestIdRef.current + 1
    searchRequestIdRef.current = reqId
    const res = query.trim()
      ? await searchConversations(query)
      : await fetchConversations()
    if (searchRequestIdRef.current !== reqId) return
    if (res.ok) {
      setConversations((prev) => {
        const prevMap = new Map(prev.map((c) => [c.id, c]))
        return res.conversations.map((item) =>
          mapSummaryToUiConversation(item, prevMap.get(item.conversation_id))
        )
      })
    }
  }, [])

  const verifyBackendHealth = useCallback(async () => {
    const status = await checkBackendHealth()
    setBackendHealth(status)
    if (status.connected) {
      const [directory] = await Promise.all([
        fetchFaqDirectory(),
        refreshConversations(''),
      ])
      if (directory) {
        setFaqDirectory(directory)
      }
    }
  }, [refreshConversations])

  // Perform a single health, FAQ directory, and SQLite conversation history load on mount
  useEffect(() => {
    let isMounted = true
    async function initializeBackendData() {
      setIsLoadingHistory(true)
      const status = await checkBackendHealth()
      if (!isMounted) return
      setBackendHealth(status)
      if (status.connected) {
        const [directory, convRes] = await Promise.all([
          fetchFaqDirectory(),
          fetchConversations(),
        ])
        if (!isMounted) return
        if (directory) {
          setFaqDirectory(directory)
        }
        if (convRes.ok) {
          setConversations(
            convRes.conversations.map((item) => mapSummaryToUiConversation(item))
          )
        }
      }
      if (isMounted) {
        setIsLoadingHistory(false)
      }
    }
    initializeBackendData()
    return () => {
      isMounted = false
    }
  }, [])

  const handleSearchChange = useCallback(async (nextQuery) => {
    setSearchQuery(nextQuery)
    const reqId = searchRequestIdRef.current + 1
    searchRequestIdRef.current = reqId
    setIsSearching(true)
    const res = nextQuery.trim()
      ? await searchConversations(nextQuery)
      : await fetchConversations()
    if (searchRequestIdRef.current !== reqId) return
    setIsSearching(false)
    if (res.ok) {
      setConversations((prev) => {
        const prevMap = new Map(prev.map((c) => [c.id, c]))
        return res.conversations.map((item) =>
          mapSummaryToUiConversation(item, prevMap.get(item.conversation_id))
        )
      })
    }
  }, [])

  const handleClearSearch = useCallback(() => {
    handleSearchChange('')
  }, [handleSearchChange])

  const activeConversation = useMemo(
    () => conversations.find((c) => c.id === activeConversationId) || null,
    [conversations, activeConversationId]
  )

  const activeBackendConversationId =
    activeConversation?.conversationId || null
  const activeTopicCategory = activeConversation?.lastCategory || null

  const invalidatePendingRequest = () => {
    activeRequestIdRef.current += 1
  }

  /**
   * Start a fresh conversation without deleting existing saved conversations.
   */
  const handleNewChat = () => {
    invalidatePendingRequest()
    setIsTyping(false)
    setActiveConversationId(null)
    setMessages([])
    setStatusBanner(null)
    setActiveNav('home')
  }

  /**
   * Reopen a saved conversation from SQLite via GET /api/conversations/<id>,
   * restoring its complete chronological message history and backend context.
   */
  const handleSelectConversation = async (convId) => {
    const target = conversations.find((c) => c.id === convId)
    if (!target) return

    const requestId = activeRequestIdRef.current + 1
    activeRequestIdRef.current = requestId
    setIsTyping(false)
    setStatusBanner(null)
    setActiveConversationId(target.id)
    setActiveNav('home')

    if (Array.isArray(target.messages)) {
      setMessages(target.messages)
    } else {
      setMessages([])
    }

    if (!target.conversationId) return

    const detailRes = await fetchConversationDetail(target.conversationId)
    if (activeRequestIdRef.current !== requestId) {
      return
    }

    if (!detailRes.ok) {
      setStatusBanner({
        type: 'error',
        message: detailRes.error || 'Could not load conversation history.',
      })
      return
    }

    const detail = detailRes.conversation
    const restoredMessages = Array.isArray(detail.messages)
      ? detail.messages.map(mapStoredMessageToUiMessage)
      : []

    setMessages(restoredMessages)
    setConversations((prev) =>
      prev.map((c) =>
        c.id === target.id
          ? {
              ...c,
              title: detail.title || c.title,
              isTitleCustom: Boolean(detail.is_title_custom),
              updatedAtIso: detail.updated_at || c.updatedAtIso,
              lastCategory: detail.last_category ?? c.lastCategory,
              lastFaqId: detail.last_faq_id ?? c.lastFaqId,
              messageCount: restoredMessages.length,
              messages: restoredMessages,
            }
          : c
      )
    )
  }

  /**
   * Reset the currently active conversation on the backend via
   * POST /api/conversations/reset and clear its frontend state.
   */
  const handleResetChat = async () => {
    if (isTyping) return
    invalidatePendingRequest()

    const currentConv = conversations.find(
      (c) => c.id === activeConversationId
    )
    const backendConvId = currentConv?.conversationId || null

    if (backendConvId) {
      const resetResult = await resetConversation(backendConvId)

      if (resetResult.connectionError) {
        setBackendHealth((prev) => ({
          ...prev,
          connected: false,
          chatbotStatus: 'disconnected',
        }))
        setStatusBanner({
          type: 'error',
          message: resetResult.message,
        })
        return
      }

      if (!resetResult.ok && !resetResult.notFound) {
        setStatusBanner({
          type: 'error',
          message: resetResult.message,
        })
        return
      }
    }

    // Clear only the active conversation from state and start fresh
    if (activeConversationId) {
      setConversations((prev) =>
        prev.filter((c) => c.id !== activeConversationId)
      )
    }
    setActiveConversationId(null)
    setMessages([])
    setStatusBanner({
      type: 'info',
      message:
        'Conversation context has been reset. Your next question will start a new session.',
    })
  }

  /**
   * Open the rename dialog for a selected conversation.
   */
  const handleRequestRenameConversation = (conv) => {
    setRenameError('')
    setRenameTarget(conv)
  }

  const handleConfirmRename = async (conv, newTitle) => {
    if (!conv) return
    if (!conv.conversationId) {
      setConversations((prev) =>
        prev.map((c) =>
          c.id === conv.id ? { ...c, title: newTitle, isTitleCustom: true } : c
        )
      )
      setRenameTarget(null)
      return
    }

    setIsRenaming(true)
    setRenameError('')
    const res = await renameConversation(conv.conversationId, newTitle)
    setIsRenaming(false)

    if (!res.ok) {
      setRenameError(res.error || 'Failed to rename conversation.')
      return
    }

    const updated = res.conversation
    setConversations((prev) =>
      prev.map((c) =>
        c.id === conv.id || c.conversationId === conv.conversationId
          ? {
              ...c,
              title: updated.title,
              isTitleCustom: true,
              updatedAtIso: updated.updated_at || c.updatedAtIso,
            }
          : c
      )
    )
    setRenameTarget(null)
  }

  /**
   * Open the confirmation dialog before deleting an individual conversation.
   */
  const handleRequestDeleteConversation = (conv) => {
    setDeleteError('')
    setDeleteTarget(conv)
  }

  const handleConfirmDelete = async (conv) => {
    if (!conv) return
    if (conv.conversationId) {
      setIsDeleting(true)
      setDeleteError('')
      const res = await deleteConversationById(conv.conversationId)
      setIsDeleting(false)

      if (!res.ok && !res.notFound) {
        setDeleteError(res.error || 'Failed to delete conversation.')
        return
      }
    }

    setConversations((prev) =>
      prev.filter(
        (c) =>
          c.id !== conv.id &&
          (!conv.conversationId || c.conversationId !== conv.conversationId)
      )
    )

    if (
      activeConversationId === conv.id ||
      (conv.conversationId && activeConversationId === conv.conversationId)
    ) {
      invalidatePendingRequest()
      setIsTyping(false)
      setActiveConversationId(null)
      setMessages([])
      setStatusBanner(null)
    }

    setDeleteTarget(null)
  }

  /**
   * Clear all saved conversations from the sidebar and reset their server-side
   * contexts on the backend.
   */
  const handleClearAllHistory = async () => {
    const backendIdsToReset = conversations
      .map((c) => c.conversationId)
      .filter(Boolean)

    invalidatePendingRequest()
    setIsTyping(false)
    setConversations([])
    setActiveConversationId(null)
    setMessages([])
    setStatusBanner(null)

    await Promise.allSettled(
      backendIdsToReset.map((id) => deleteConversationById(id))
    )
  }

  /**
   * Send a user question (or selected clarification/follow-up question) to
   * POST /api/chat while maintaining per-conversation backend conversation_id.
   */
  const handleSendMessage = async (text) => {
    const trimmed = typeof text === 'string' ? text.trim() : ''
    if (!trimmed || isTyping) return

    const requestId = activeRequestIdRef.current + 1
    activeRequestIdRef.current = requestId
    setStatusBanner(null)

    const userMsg = {
      id: `user-${Date.now()}`,
      sender: 'user',
      text: trimmed,
      timestamp: formatCurrentTime(),
    }

    const updatedWithUser = [...messages, userMsg]
    setMessages(updatedWithUser)
    setSessionQuestionsCount((prev) => prev + 1)
    setIsTyping(true)
    setActiveNav('home')

    // Identify whether we are continuing an existing conversation or starting a new one
    let localConvKey = activeConversationId
    const existingConv = conversations.find((c) => c.id === localConvKey)
    let backendConvId = existingConv?.conversationId || null

    const shortTitle =
      trimmed.length > 36 ? `${trimmed.slice(0, 36)}...` : trimmed

    if (!localConvKey) {
      // Temporary UI key until the backend returns its authoritative conversation_id
      localConvKey = `pending-${Date.now()}`
      setActiveConversationId(localConvKey)
      const newConv = {
        id: localConvKey,
        conversationId: null,
        title: shortTitle,
        updatedAt: 'Just now',
        lastCategory: null,
        lastFaqId: null,
        messages: updatedWithUser,
      }
      setConversations((prev) => [newConv, ...prev])
    } else {
      setConversations((prev) =>
        prev.map((c) =>
          c.id === localConvKey
            ? { ...c, updatedAt: 'Just now', messages: updatedWithUser }
            : c
        )
      )
    }

    // Send request to Flask POST /api/chat (only passing backendConvId if obtained from backend)
    let result = await sendChatMessage(trimmed, backendConvId)

    // If the backend session expired (e.g. server restarted or LRU-evicted),
    // recover gracefully by requesting a fresh backend conversation_id.
    let sessionRenewed = false
    if (result.expiredSessionError && backendConvId) {
      sessionRenewed = true
      backendConvId = null
      result = await sendChatMessage(trimmed, null)
    }

    // Ignore stale response if the user switched or reset chat while in flight
    if (activeRequestIdRef.current !== requestId) {
      return
    }

    if (result.connectionError) {
      setBackendHealth((prev) => ({
        ...prev,
        connected: false,
        chatbotStatus: 'disconnected',
      }))
    } else {
      setBackendHealth((prev) => ({
        ...prev,
        connected: true,
        chatbotStatus: 'ready',
      }))
      // Lazily populate FAQ directory if backend came online after initial mount
      if (faqDirectory.faqs.length === 0) {
        fetchFaqDirectory().then((dir) => {
          if (dir) setFaqDirectory(dir)
        })
      }
    }

    if (sessionRenewed && result.ok) {
      setStatusBanner({
        type: 'info',
        message:
          'Your previous server session had expired; a new conversation context was started automatically.',
      })
    }

    const { data } = result
    const returnedBackendConvId = data.conversation_id || backendConvId || null
    const finalConvKey = returnedBackendConvId || localConvKey

    // Collect FAQ IDs already answered in this conversation to avoid repeating them in follow-ups
    const answeredFaqIds = new Set()
    for (const m of updatedWithUser) {
      if (m.sender !== 'assistant') continue
      if (m.matchType === 'clear_match' && m.faqId != null) {
        answeredFaqIds.add(m.faqId)
      }
      if (Array.isArray(m.subResponses)) {
        for (const sub of m.subResponses) {
          if (sub && sub.match_type === 'clear_match' && sub.faq_id != null) {
            answeredFaqIds.add(sub.faq_id)
          }
        }
      }
    }
    if (Array.isArray(data.sub_responses)) {
      for (const sub of data.sub_responses) {
        if (sub && sub.match_type === 'clear_match' && sub.faq_id != null) {
          answeredFaqIds.add(sub.faq_id)
        }
      }
    }

    const followUpSuggestions = computeSmartFollowUps({
      matchType: data.match_type,
      fallback: data.fallback,
      needsClarification: data.needs_clarification,
      faqId: data.faq_id,
      category: data.category,
      matchedQuestion: data.matched_question,
      candidates: data.candidates,
      allFaqs: faqDirectory.faqs,
      answeredFaqIds,
    })

    const assistantMsg = {
      id: `bot-${Date.now()}`,
      sender: 'assistant',
      text: data.answer,
      matchedQuestion: data.matched_question,
      category: data.category,
      confidence: data.confidence,
      faqId: data.faq_id,
      fallback: data.fallback,
      matchType: data.match_type,
      candidates: data.candidates || [],
      needsClarification: Boolean(data.needs_clarification),
      clarificationMessage: data.clarification_message,
      isMultiIntent: Boolean(data.is_multi_intent),
      subResponses: Array.isArray(data.sub_responses) ? data.sub_responses : [],
      answerSource: data.answer_source || 'faq',
      documentSources: Array.isArray(data.document_sources)
        ? data.document_sources
        : [],
      supportingPassages: Array.isArray(data.supporting_passages)
        ? data.supporting_passages
        : [],
      sourceConflict: Boolean(data.source_conflict),
      followUpSuggestions,
      success: data.success,
      isConnectionError: Boolean(result.connectionError),
      timestamp: formatCurrentTime(),
    }

    const finalMessages = [...updatedWithUser, assistantMsg]

    setMessages(finalMessages)
    setActiveConversationId(finalConvKey)
    setConversations((prev) =>
      prev.map((c) => {
        if (c.id !== localConvKey && c.id !== finalConvKey) {
          return c
        }
        const resolvedCategory =
          data.match_type === 'clear_match' && data.category
            ? data.category
            : c.lastCategory
        const resolvedFaqId =
          data.match_type === 'clear_match' && data.faq_id != null
            ? data.faq_id
            : c.lastFaqId

        return {
          ...c,
          id: finalConvKey,
          conversationId: returnedBackendConvId,
          title:
            !c.isTitleCustom && data.conversation_title
              ? data.conversation_title
              : c.title,
          updatedAtIso: new Date().toISOString(),
          updatedAt: 'Just now',
          lastCategory: resolvedCategory,
          lastFaqId: resolvedFaqId,
          messageCount: finalMessages.length,
          messages: finalMessages,
        }
      })
    )
    setIsTyping(false)
  }

  const togglePreference = (key) => {
    setPreferences((prev) => ({
      ...prev,
      [key]: !prev[key],
    }))
  }

  if (currentPath.startsWith('/admin')) {
    return (
      <AdminLayout
        currentPath={currentPath}
        onNavigate={navigate}
        onExitAdmin={() => navigate('/')}
      />
    )
  }

  return (
    <div className="app-layout">
      <Sidebar
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed((prev) => !prev)}
        isMobileOpen={isMobileSidebarOpen}
        onCloseMobile={() => setIsMobileSidebarOpen(false)}
        activeNav={activeNav}
        onSelectNav={setActiveNav}
        conversations={conversations}
        activeConversationId={activeConversationId}
        searchQuery={searchQuery}
        isSearching={isSearching}
        isLoadingHistory={isLoadingHistory}
        onSearchChange={handleSearchChange}
        onClearSearch={handleClearSearch}
        onSelectConversation={handleSelectConversation}
        onRequestRenameConversation={handleRequestRenameConversation}
        onRequestDeleteConversation={handleRequestDeleteConversation}
        onNewChat={handleNewChat}
        onOpenHelp={() => setIsHelpOpen(true)}
        onOpenSettings={() => setIsSettingsOpen(true)}
        onOpenAdmin={() => navigate('/admin')}
      />

      <ChatWindow
        messages={messages}
        isTyping={isTyping}
        onSendMessage={handleSendMessage}
        onNewChat={handleNewChat}
        onResetChat={handleResetChat}
        onOpenMobileSidebar={() => setIsMobileSidebarOpen(true)}
        onOpenHelp={() => setIsHelpOpen(true)}
        preferences={preferences}
        backendHealth={backendHealth}
        onRecheckHealth={verifyBackendHealth}
        activeNav={activeNav}
        onSelectNav={setActiveNav}
        faqDirectory={faqDirectory}
        sessionQuestionsCount={sessionQuestionsCount}
        activeBackendConversationId={activeBackendConversationId}
        activeTopicCategory={activeTopicCategory}
        statusBanner={statusBanner}
        onDismissBanner={() => setStatusBanner(null)}
      />

      {/* Help & FAQ Guide Modal */}
      {isHelpOpen && (
        <div
          className="modal-backdrop"
          onClick={() => setIsHelpOpen(false)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="help-modal-title"
        >
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title-group">
                <div className="modal-icon">
                  <BookOpen size={18} strokeWidth={2} />
                </div>
                <div>
                  <h2 id="help-modal-title">IntelliFAQ Guide &amp; Help</h2>
                  <p>How our NLP FAQ Assistant resolves your queries</p>
                </div>
              </div>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setIsHelpOpen(false)}
                aria-label="Close help modal"
              >
                <X size={18} />
              </button>
            </div>

            <div className="modal-body">
              <div className="help-info-box">
                <div className="help-info-title">
                  <Sparkles size={15} />
                  <span>About IntelliFAQ 2.0</span>
                </div>
                <p>
                  IntelliFAQ matches your natural language questions against an
                  institutional FAQ dataset using text preprocessing, TF-IDF
                  vectorization, top-3 candidate ranking, and context-aware
                  multi-turn conversation tracking.
                </p>
              </div>

              <h3 className="modal-section-heading">Quick-Ask FAQ Topics</h3>
              <div className="help-topic-list">
                {[
                  {
                    label: 'Admission requirements',
                    query:
                      'What are the admission requirements for undergraduate programs?',
                  },
                  {
                    label: 'Fee payment',
                    query: 'How can I pay my semester tuition fees?',
                  },
                  {
                    label: 'Attendance policy',
                    query:
                      'What is the minimum attendance policy required for appearing in exams?',
                  },
                  {
                    label: 'Examination schedule',
                    query:
                      'Where can I check the upcoming semester examination schedule?',
                  },
                ].map((topic) => (
                  <button
                    key={topic.label}
                    type="button"
                    className="help-topic-btn"
                    onClick={() => {
                      setIsHelpOpen(false)
                      handleSendMessage(topic.query)
                    }}
                  >
                    <span>{topic.label}</span>
                    <span className="help-ask-pill">Ask now →</span>
                  </button>
                ))}
              </div>

              <h3 className="modal-section-heading">Keyboard Shortcuts</h3>
              <div className="shortcuts-grid">
                <div className="shortcut-row">
                  <span>Send message</span>
                  <kbd>Enter</kbd>
                </div>
                <div className="shortcut-row">
                  <span>Insert new line</span>
                  <kbd>Shift + Enter</kbd>
                </div>
              </div>
            </div>

            <div className="modal-footer">
              <button
                type="button"
                className="modal-primary-btn"
                onClick={() => setIsHelpOpen(false)}
              >
                Got it
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Settings Modal */}
      {isSettingsOpen && (
        <div
          className="modal-backdrop"
          onClick={() => setIsSettingsOpen(false)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="settings-modal-title"
        >
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title-group">
                <div className="modal-icon">
                  <Sliders size={18} strokeWidth={2} />
                </div>
                <div>
                  <h2 id="settings-modal-title">Workspace Settings</h2>
                  <p>Customize your IntelliFAQ chat interface</p>
                </div>
              </div>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setIsSettingsOpen(false)}
                aria-label="Close settings modal"
              >
                <X size={18} />
              </button>
            </div>

            <div className="modal-body">
              <div className="settings-list">
                <label className="setting-item">
                  <div className="setting-text">
                    <span className="setting-name">Show Message Timestamps</span>
                    <span className="setting-desc">
                      Display time sent alongside each message bubble
                    </span>
                  </div>
                  <input
                    type="checkbox"
                    checked={preferences.showTimestamps}
                    onChange={() => togglePreference('showTimestamps')}
                    className="setting-checkbox"
                  />
                </label>

                <label className="setting-item">
                  <div className="setting-text">
                    <span className="setting-name">Auto-Scroll Conversation</span>
                    <span className="setting-desc">
                      Automatically scroll to new replies as they arrive
                    </span>
                  </div>
                  <input
                    type="checkbox"
                    checked={preferences.autoScroll}
                    onChange={() => togglePreference('autoScroll')}
                    className="setting-checkbox"
                  />
                </label>

                <label className="setting-item">
                  <div className="setting-text">
                    <span className="setting-name">Compact Message Spacing</span>
                    <span className="setting-desc">
                      Fit more messages on screen with tighter vertical padding
                    </span>
                  </div>
                  <input
                    type="checkbox"
                    checked={preferences.compactMode}
                    onChange={() => togglePreference('compactMode')}
                    className="setting-checkbox"
                  />
                </label>
              </div>

              <div className="settings-danger-zone">
                <div className="danger-text">
                  <span className="setting-name">Conversation History</span>
                  <span className="setting-desc">
                    {conversations.length} saved conversation(s) in sidebar
                  </span>
                </div>
                <button
                  type="button"
                  className="danger-btn"
                  onClick={handleClearAllHistory}
                  disabled={conversations.length === 0}
                >
                  <Trash2 size={14} />
                  <span>Clear History</span>
                </button>
              </div>
            </div>

            <div className="modal-footer">
              <button
                type="button"
                className="modal-primary-btn"
                onClick={() => setIsSettingsOpen(false)}
              >
                <CheckCircle2 size={15} />
                <span>Done</span>
              </button>
            </div>
          </div>
        </div>
      )}
      <RenameConversationDialog
        key={renameTarget?.id || 'rename-dialog'}
        conversation={renameTarget}
        isSaving={isRenaming}
        errorMessage={renameError}
        onSave={handleConfirmRename}
        onCancel={() => setRenameTarget(null)}
      />

      <DeleteConversationDialog
        conversation={deleteTarget}
        isDeleting={isDeleting}
        errorMessage={deleteError}
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}

export default App
