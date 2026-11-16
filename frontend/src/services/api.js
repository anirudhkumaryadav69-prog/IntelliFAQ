/**
 * IntelliFAQ 2.0 Backend API Service
 *
 * Centralizes all HTTP communication between the React frontend and the
 * Flask NLP & Context-Aware Conversation REST API:
 * - GET  /api/health              (checkBackendHealth)
 * - GET  /api/faqs                (fetchFaqDirectory)
 * - POST /api/chat                (sendChatMessage with optional conversation_id)
 * - POST /api/conversations/reset (resetConversation)
 *
 * Default base URL: http://127.0.0.1:5000 (overridable via VITE_API_BASE_URL).
 */

const DEFAULT_HOST =
  typeof window !== 'undefined' && window.location?.hostname
    ? window.location.hostname
    : '127.0.0.1'

const RAW_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || `http://${DEFAULT_HOST}:5000`

export const API_BASE_URL = RAW_BASE_URL.replace(/\/+$/, '')

export const CONNECTION_ERROR_MESSAGE =
  'Unable to connect to the IntelliFAQ server. Please make sure the backend is running and try again.'

export const RESET_CONNECTION_ERROR_MESSAGE =
  'Unable to reset conversation context on the server because the IntelliFAQ backend is unreachable. Please make sure the backend is running and try again.'

/**
 * Safely parse JSON from a fetch Response object without throwing on empty bodies.
 */
async function parseJsonSafely(response) {
  const text = await response.text()
  if (!text || !text.trim()) return null
  try {
    return JSON.parse(text)
  } catch {
    throw new Error('Received an invalid JSON response from the server.')
  }
}

/**
 * Normalize the candidate array returned by the backend NLP engine.
 */
function normalizeCandidates(candidates) {
  if (!Array.isArray(candidates)) return []
  return candidates
    .filter(
      (item) =>
        item &&
        typeof item === 'object' &&
        typeof item.question === 'string' &&
        item.question.trim()
    )
    .map((item) => ({
      faq_id: item.faq_id ?? null,
      question: item.question.trim(),
      category:
        typeof item.category === 'string' && item.category.trim()
          ? item.category.trim()
          : 'General',
      similarity:
        typeof item.similarity === 'number' ? item.similarity : 0,
    }))
}

/**
 * Normalize individual sub-response objects returned for multi-intent queries.
 */
function normalizeSubResponses(subResponses) {
  if (!Array.isArray(subResponses)) return []
  return subResponses
    .filter((sub) => sub && typeof sub === 'object')
    .map((sub) => {
      const subConfidence =
        typeof sub.confidence === 'number' ? sub.confidence : 0
      const rawMatchType =
        sub.match_type === 'clear_match' ||
        sub.match_type === 'ambiguous_match' ||
        sub.match_type === 'no_reliable_match'
          ? sub.match_type
          : sub.fallback
          ? 'no_reliable_match'
          : subConfidence >= 34
          ? 'clear_match'
          : 'ambiguous_match'
      const subMatchType =
        rawMatchType === 'clear_match' && subConfidence < 34
          ? 'ambiguous_match'
          : rawMatchType

      return {
        query:
          typeof sub.query === 'string' && sub.query.trim()
            ? sub.query.trim()
            : '',
        answer:
          typeof sub.answer === 'string' && sub.answer.trim()
            ? sub.answer.trim()
            : '',
        matched_question: sub.matched_question ?? null,
        category: sub.category ?? null,
        confidence: subConfidence,
        faq_id: sub.faq_id ?? null,
        fallback: Boolean(sub.fallback),
        match_type: subMatchType,
        candidates: normalizeCandidates(sub.candidates),
        needs_clarification:
          Boolean(sub.needs_clarification) ||
          subMatchType === 'ambiguous_match',
        clarification_message:
          typeof sub.clarification_message === 'string' &&
          sub.clarification_message.trim()
            ? sub.clarification_message.trim()
            : null,
      }
    })
}

/**
 * Check backend health and readiness via GET /api/health.
 *
 * @returns {Promise<{connected: boolean, chatbotStatus: string, faqCount: number, message: string}>}
 */
export async function checkBackendHealth() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/health`, {
      method: 'GET',
      headers: {
        Accept: 'application/json',
      },
    })

    const data = await parseJsonSafely(response)

    if (
      response.ok &&
      data &&
      data.success &&
      data.chatbot_status === 'ready'
    ) {
      return {
        connected: true,
        chatbotStatus: data.chatbot_status,
        faqCount: typeof data.faq_count === 'number' ? data.faq_count : 0,
        message: data.message || 'Connected',
      }
    }

    return {
      connected: false,
      chatbotStatus: data?.chatbot_status || 'unavailable',
      faqCount: typeof data?.faq_count === 'number' ? data.faq_count : 0,
      message: data?.message || 'Backend NLP engine is unavailable.',
    }
  } catch {
    return {
      connected: false,
      chatbotStatus: 'disconnected',
      faqCount: 0,
      message: CONNECTION_ERROR_MESSAGE,
    }
  }
}

/**
 * Retrieve the public FAQ knowledge base directory via GET /api/faqs.
 * Used both for the Overview telemetry dashboard and for dynamically selecting
 * same-category smart follow-up suggestions.
 *
 * @returns {Promise<{
 *   totalCount: number,
 *   categories: string[],
 *   faqs: Array<{id: number, question: string, category: string}>,
 *   distribution: Array<{category: string, count: number, sampleQuestion: string | null}>
 * } | null>}
 */
export async function fetchFaqDirectory() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/faqs`, {
      method: 'GET',
      headers: {
        Accept: 'application/json',
      },
    })

    if (!response.ok) return null
    const data = await parseJsonSafely(response)
    if (!data || !data.success || !Array.isArray(data.faqs)) return null

    const countsMap = {}
    const sampleMap = {}
    const sanitizedFaqs = []

    for (const item of data.faqs) {
      if (!item || typeof item.question !== 'string' || !item.question.trim()) {
        continue
      }
      const cat =
        typeof item.category === 'string' && item.category.trim()
          ? item.category.trim()
          : 'Uncategorized'
      const question = item.question.trim()

      sanitizedFaqs.push({
        id: item.id,
        question,
        category: cat,
      })

      countsMap[cat] = (countsMap[cat] || 0) + 1
      if (!sampleMap[cat]) {
        sampleMap[cat] = question
      }
    }

    const categories = Array.isArray(data.categories)
      ? data.categories
      : Object.keys(countsMap)

    const distribution = categories.map((category) => ({
      category,
      count: countsMap[category] || 0,
      sampleQuestion: sampleMap[category] || null,
    }))

    return {
      totalCount:
        typeof data.total_count === 'number'
          ? data.total_count
          : sanitizedFaqs.length,
      categories,
      faqs: sanitizedFaqs,
      distribution,
    }
  } catch {
    return null
  }
}

/**
 * Send a user question to POST /api/chat with optional conversation_id.
 *
 * @param {string} message - The user's natural language question.
 * @param {string | null} [conversationId=null] - Existing backend conversation ID, if any.
 * @returns {Promise<{
 *   ok: boolean,
 *   status: number,
 *   connectionError?: boolean,
 *   validationError?: boolean,
 *   expiredSessionError?: boolean,
 *   data: {
 *     success: boolean,
 *     answer: string,
 *     matched_question: string | null,
 *     category: string | null,
 *     confidence: number,
 *     faq_id: number | null,
 *     fallback: boolean,
 *     match_type: 'clear_match' | 'ambiguous_match' | 'no_reliable_match',
 *     candidates: Array<{faq_id: number | null, question: string, category: string, similarity: number}>,
 *     needs_clarification: boolean,
 *     clarification_message: string | null,
 *     conversation_id: string | null,
 *     error?: string
 *   }
 * }>}
 */
export async function sendChatMessage(message, conversationId = null) {
  const payload = { message }
  if (typeof conversationId === 'string' && conversationId.trim()) {
    payload.conversation_id = conversationId.trim()
  }

  try {
    const response = await fetch(`${API_BASE_URL}/api/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify(payload),
    })

    const data = await parseJsonSafely(response)

    if (!data || typeof data !== 'object') {
      return {
        ok: false,
        status: response.status,
        data: {
          success: false,
          answer:
            'Received an unexpected response format from the IntelliFAQ server.',
          matched_question: null,
          category: null,
          confidence: 0,
          faq_id: null,
          fallback: true,
          match_type: 'no_reliable_match',
          candidates: [],
          needs_clarification: false,
          clarification_message: null,
          conversation_id: null,
        },
      }
    }

    // Handle HTTP 400 validation errors (including unknown/expired conversation_id)
    if (response.status === 400) {
      const errorText = typeof data.error === 'string' ? data.error : ''
      const isExpiredSession =
        errorText.toLowerCase().includes('conversation_id') &&
        (errorText.toLowerCase().includes('unknown') ||
          errorText.toLowerCase().includes('expired'))

      return {
        ok: false,
        status: 400,
        validationError: true,
        expiredSessionError: isExpiredSession,
        data: {
          success: false,
          answer:
            data.answer ||
            data.error ||
            'Please enter a valid question so I can search the FAQ knowledge base.',
          matched_question: null,
          category: null,
          confidence: 0,
          faq_id: null,
          fallback: true,
          match_type: 'no_reliable_match',
          candidates: [],
          needs_clarification: false,
          clarification_message: null,
          conversation_id: null,
          error: data.error,
        },
      }
    }

    // Handle HTTP 500 / 503 server errors gracefully
    if (!response.ok) {
      return {
        ok: false,
        status: response.status,
        data: {
          success: false,
          answer:
            data.answer ||
            data.error ||
            'The IntelliFAQ server encountered an error while processing your request. Please try again.',
          matched_question: null,
          category: null,
          confidence: 0,
          faq_id: null,
          fallback: true,
          match_type: 'no_reliable_match',
          candidates: [],
          needs_clarification: false,
          clarification_message: null,
          conversation_id: null,
          error: data.error,
        },
      }
    }

    const confidenceVal =
      typeof data.confidence === 'number' ? data.confidence : 0
    const normalizedSubResponses = normalizeSubResponses(data.sub_responses)
    const isMultiIntent =
      Boolean(data.is_multi_intent) && normalizedSubResponses.length > 1

    const rawMatchType =
      data.match_type === 'clear_match' ||
      data.match_type === 'ambiguous_match' ||
      data.match_type === 'no_reliable_match'
        ? data.match_type
        : data.fallback
        ? 'no_reliable_match'
        : 'clear_match'

    const isDocumentGrounded =
      data.answer_source === 'document' ||
      (Boolean(data.evidence_sufficient) &&
        Array.isArray(data.document_sources) &&
        data.document_sources.length > 0)

    const normalizedCandidates = normalizeCandidates(data.candidates)

    const matchType =
      !isMultiIntent &&
      !isDocumentGrounded &&
      rawMatchType === 'clear_match' &&
      confidenceVal < 34 &&
      normalizedCandidates.length > 0
        ? 'ambiguous_match'
        : rawMatchType

    const needsClarification =
      normalizedCandidates.length > 0 &&
      (Boolean(data.needs_clarification) ||
        (!isMultiIntent && matchType === 'ambiguous_match'))

    return {
      ok: true,
      status: 200,
      data: {
        success: Boolean(data.success),
        answer:
          typeof data.answer === 'string' && data.answer.trim()
            ? data.answer
            : 'No answer was returned by the FAQ engine.',
        matched_question: data.matched_question ?? null,
        category: data.category ?? null,
        confidence: confidenceVal,
        faq_id: data.faq_id ?? null,
        fallback: Boolean(data.fallback),
        match_type: matchType,
        candidates: normalizedCandidates,
        needs_clarification: needsClarification,
        clarification_message:
          typeof data.clarification_message === 'string' &&
          data.clarification_message.trim()
            ? data.clarification_message.trim()
            : null,
        is_multi_intent: isMultiIntent,
        sub_responses: normalizedSubResponses,
        conversation_id:
          typeof data.conversation_id === 'string' &&
          data.conversation_id.trim()
            ? data.conversation_id.trim()
            : null,
        conversation_title:
          typeof data.conversation_title === 'string' &&
          data.conversation_title.trim()
            ? data.conversation_title.trim()
            : null,
        answer_source: data.answer_source || 'faq',
        document_sources: Array.isArray(data.document_sources)
          ? data.document_sources
          : [],
        supporting_passages: Array.isArray(data.supporting_passages)
          ? data.supporting_passages
          : [],
        retrieval_confidence:
          typeof data.retrieval_confidence === 'number'
            ? data.retrieval_confidence
            : confidenceVal,
        source_conflict: Boolean(data.source_conflict),
        evidence_sufficient:
          data.evidence_sufficient !== undefined
            ? Boolean(data.evidence_sufficient)
            : !data.fallback,
      },
    }
  } catch {
    return {
      ok: false,
      status: 0,
      connectionError: true,
      data: {
        success: false,
        answer: CONNECTION_ERROR_MESSAGE,
        matched_question: null,
        category: null,
        confidence: 0,
        faq_id: null,
        fallback: true,
        match_type: 'no_reliable_match',
        candidates: [],
        needs_clarification: false,
        clarification_message: null,
        conversation_id: null,
      },
    }
  }
}

/**
 * Reset a specific conversation on the backend via POST /api/conversations/reset.
 *
 * @param {string} conversationId - The backend conversation_id to reset.
 * @returns {Promise<{
 *   ok: boolean,
 *   status: number,
 *   notFound?: boolean,
 *   connectionError?: boolean,
 *   conversationId: string | null,
 *   message: string
 * }>}
 */
export async function resetConversation(conversationId) {
  if (typeof conversationId !== 'string' || !conversationId.trim()) {
    return {
      ok: false,
      status: 400,
      conversationId: null,
      message: 'A valid conversation_id is required to reset a conversation.',
    }
  }

  const cleanedId = conversationId.trim()

  try {
    const response = await fetch(`${API_BASE_URL}/api/conversations/reset`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify({ conversation_id: cleanedId }),
    })

    const data = await parseJsonSafely(response)

    if (response.ok && data && data.success) {
      return {
        ok: true,
        status: response.status,
        conversationId: data.conversation_id || cleanedId,
        message: data.message || 'Conversation reset successfully.',
      }
    }

    if (response.status === 404) {
      return {
        ok: false,
        status: 404,
        notFound: true,
        conversationId: cleanedId,
        message:
          data?.error ||
          'Conversation session was already expired or not found on the server.',
      }
    }

    return {
      ok: false,
      status: response.status,
      conversationId: cleanedId,
      message:
        data?.error || 'Failed to reset conversation on the server.',
    }
  } catch {
    return {
      ok: false,
      status: 0,
      connectionError: true,
      conversationId: cleanedId,
      message: RESET_CONNECTION_ERROR_MESSAGE,
    }
  }
}

/**
 * List persisted conversations from SQLite via GET /api/conversations.
 */
export async function fetchConversations() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/conversations`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
    })
    const data = await parseJsonSafely(response)
    if (response.ok && data && data.success && Array.isArray(data.conversations)) {
      return { ok: true, conversations: data.conversations }
    }
    return { ok: false, conversations: [], error: data?.error || 'Failed to load conversations.' }
  } catch {
    return { ok: false, conversations: [], connectionError: true, error: CONNECTION_ERROR_MESSAGE }
  }
}

/**
 * Search persisted conversations by title or message content via GET /api/conversations/search.
 */
export async function searchConversations(query) {
  const cleaned = typeof query === 'string' ? query.trim() : ''
  if (!cleaned) {
    return fetchConversations()
  }
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/conversations/search?q=${encodeURIComponent(cleaned)}`,
      {
        method: 'GET',
        headers: { Accept: 'application/json' },
      }
    )
    const data = await parseJsonSafely(response)
    if (response.ok && data && data.success && Array.isArray(data.conversations)) {
      return { ok: true, conversations: data.conversations }
    }
    return { ok: false, conversations: [], error: data?.error || 'Search failed.' }
  } catch {
    return { ok: false, conversations: [], connectionError: true, error: CONNECTION_ERROR_MESSAGE }
  }
}

/**
 * Retrieve complete conversation history and restorable context via GET /api/conversations/<id>.
 */
export async function fetchConversationDetail(conversationId) {
  if (typeof conversationId !== 'string' || !conversationId.trim()) {
    return { ok: false, status: 400, error: 'Invalid conversation ID.' }
  }
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/conversations/${encodeURIComponent(conversationId.trim())}`,
      {
        method: 'GET',
        headers: { Accept: 'application/json' },
      }
    )
    const data = await parseJsonSafely(response)
    if (response.ok && data && data.success && data.conversation) {
      return { ok: true, status: 200, conversation: data.conversation }
    }
    return {
      ok: false,
      status: response.status,
      error: data?.error || 'Conversation not found.',
    }
  } catch {
    return {
      ok: false,
      status: 0,
      connectionError: true,
      error: CONNECTION_ERROR_MESSAGE,
    }
  }
}

/**
 * Rename a persisted conversation via PATCH /api/conversations/<id>.
 */
export async function renameConversation(conversationId, title) {
  if (typeof conversationId !== 'string' || !conversationId.trim()) {
    return { ok: false, status: 400, error: 'Invalid conversation ID.' }
  }
  const cleanedTitle = typeof title === 'string' ? title.trim() : ''
  if (!cleanedTitle) {
    return { ok: false, status: 400, error: 'Title cannot be empty.' }
  }
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/conversations/${encodeURIComponent(conversationId.trim())}`,
      {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify({ title: cleanedTitle }),
      }
    )
    const data = await parseJsonSafely(response)
    if (response.ok && data && data.success && data.conversation) {
      return { ok: true, status: 200, conversation: data.conversation }
    }
    return {
      ok: false,
      status: response.status,
      error: data?.error || 'Failed to rename conversation.',
    }
  } catch {
    return {
      ok: false,
      status: 0,
      connectionError: true,
      error: CONNECTION_ERROR_MESSAGE,
    }
  }
}

/**
 * Permanently delete a persisted conversation via DELETE /api/conversations/<id>.
 */
export async function deleteConversationById(conversationId) {
  if (typeof conversationId !== 'string' || !conversationId.trim()) {
    return { ok: false, status: 400, error: 'Invalid conversation ID.' }
  }
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/conversations/${encodeURIComponent(conversationId.trim())}`,
      {
        method: 'DELETE',
        headers: { Accept: 'application/json' },
      }
    )
    const data = await parseJsonSafely(response)
    if (response.ok && data && data.success) {
      return { ok: true, status: 200, conversationId: data.conversation_id || conversationId }
    }
    return {
      ok: false,
      status: response.status,
      notFound: response.status === 404,
      error: data?.error || 'Failed to delete conversation.',
    }
  } catch {
    return {
      ok: false,
      status: 0,
      connectionError: true,
      error: CONNECTION_ERROR_MESSAGE,
    }
  }
}
