import { useState } from 'react'
import {
  Bot,
  User,
  Copy,
  Check,
  Tag,
  HelpCircle,
  AlertCircle,
  Sparkles,
  GitBranch,
  ArrowUpRight,
  CornerDownRight,
} from 'lucide-react'

function formatSimilarityScore(confidence) {
  if (typeof confidence === 'number') {
    return `${confidence.toFixed(1).replace(/\.0$/, '')}%`
  }
  if (typeof confidence === 'string' && confidence.trim()) {
    return confidence.includes('%') ? confidence : `${confidence}%`
  }
  return null
}

function MessageBubble({
  message,
  showTimestamps = true,
  onSelectQuestion,
  disabled = false,
}) {
  const [copied, setCopied] = useState(false)
  const [expandedSourceIdx, setExpandedSourceIdx] = useState(null)
  const isUser = message.sender === 'user'

  const isFallback = Boolean(message.fallback)
  const isConnectionError = Boolean(message.isConnectionError)
  const subResponses = Array.isArray(message.subResponses)
    ? message.subResponses
    : []
  const isMultiIntent =
    !isUser && Boolean(message.isMultiIntent) && subResponses.length > 1

  const rawMatchType =
    message.matchType ||
    (isFallback ? 'no_reliable_match' : 'clear_match')
  const isDocumentGrounded =
    message.answerSource === 'document' ||
    (Array.isArray(message.documentSources) &&
      message.documentSources.length > 0)

  const clarificationCandidates = Array.isArray(message.candidates)
    ? message.candidates.filter(
        (c) => c && typeof c.question === 'string' && c.question.trim()
      )
    : []

  const matchType =
    !isMultiIntent &&
    !isDocumentGrounded &&
    rawMatchType === 'clear_match' &&
    typeof message.confidence === 'number' &&
    message.confidence < 34 &&
    clarificationCandidates.length > 0
      ? 'ambiguous_match'
      : rawMatchType

  const needsClarification =
    !isUser &&
    !isMultiIntent &&
    clarificationCandidates.length > 0 &&
    (Boolean(message.needsClarification) || matchType === 'ambiguous_match') &&
    matchType !== 'no_reliable_match'

  const multiIntentCategories = isMultiIntent
    ? Array.from(
        new Set(
          subResponses
            .filter((s) => s && s.match_type === 'clear_match' && s.category)
            .map((s) => s.category)
        )
      )
    : []

  const followUpSuggestions =
    !isUser &&
    !isFallback &&
    !needsClarification &&
    matchType === 'clear_match' &&
    Array.isArray(message.followUpSuggestions)
      ? message.followUpSuggestions.filter(
          (s) => s && typeof s.question === 'string' && s.question.trim()
        )
      : []

  const textToCopy =
    needsClarification && message.clarificationMessage
      ? message.clarificationMessage
      : message.text

  const handleCopy = async () => {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(textToCopy)
      } else {
        const textArea = document.createElement('textarea')
        textArea.value = textToCopy
        document.body.appendChild(textArea)
        textArea.select()
        document.execCommand('copy')
        document.body.removeChild(textArea)
      }
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  const similarityLabel =
    !isFallback && !needsClarification
      ? formatSimilarityScore(message.confidence)
      : null

  return (
    <div
      className={`message-row ${
        isUser ? 'message-row-user' : 'message-row-assistant'
      }`}
    >
      <div
        className={`message-avatar ${
          isUser ? 'avatar-user' : 'avatar-assistant'
        }`}
        aria-hidden="true"
      >
        {isUser ? (
          <User size={17} strokeWidth={2} />
        ) : (
          <Bot size={18} strokeWidth={2} />
        )}
      </div>

      <div className="message-content-wrap">
        <div className="message-meta">
          <span className="message-sender">
            {isUser ? 'You' : 'IntelliFAQ'}
          </span>

          {!isUser &&
            !isMultiIntent &&
            !isFallback &&
            !needsClarification &&
            message.category && (
              <span
                className="message-category-badge"
                title="Matched FAQ Category"
              >
                <Tag size={11} strokeWidth={2} />
                {message.category}
              </span>
            )}

          {!isUser && isMultiIntent && (
            <span
              className="message-multi-intent-badge"
              title="Multiple questions detected and answered independently"
            >
              <Sparkles size={11} strokeWidth={2} />
              Multi-Topic Response ({subResponses.length})
            </span>
          )}

          {!isUser &&
            isMultiIntent &&
            multiIntentCategories.map((cat) => (
              <span
                key={cat}
                className="message-category-badge"
                title={`Matched FAQ Category: ${cat}`}
              >
                <Tag size={11} strokeWidth={2} />
                {cat}
              </span>
            ))}

          {!isUser && needsClarification && (
            <span
              className="message-clarification-badge"
              title="Multiple plausible FAQ matches found"
            >
              <GitBranch size={11} strokeWidth={2} />
              Clarification Needed
            </span>
          )}

          {showTimestamps && message.timestamp && (
            <span className="message-time">{message.timestamp}</span>
          )}
        </div>

        {/* Multi-Intent Structured Response, Clarification Card, or Single Bubble */}
        {!isUser && isMultiIntent ? (
          <div
            className="multi-intent-container"
            role="region"
            aria-label="Multi-question answers"
          >
            {subResponses.map((sub, subIdx) => {
              const subIsFallback =
                Boolean(sub.fallback) || sub.match_type === 'no_reliable_match'
              const subNeedsClarification =
                !subIsFallback &&
                (Boolean(sub.needs_clarification) ||
                  sub.match_type === 'ambiguous_match' ||
                  (typeof sub.confidence === 'number' && sub.confidence < 34))
              const subSimLabel =
                !subIsFallback && !subNeedsClarification
                  ? formatSimilarityScore(sub.confidence)
                  : null
              const subCandidates =
                subNeedsClarification && Array.isArray(sub.candidates)
                  ? sub.candidates.filter(
                      (c) =>
                        c &&
                        typeof c.question === 'string' &&
                        c.question.trim()
                    )
                  : []

              return (
                <div
                  key={`${subIdx}-${sub.faq_id ?? sub.query}`}
                  className={`multi-intent-card ${
                    subNeedsClarification
                      ? 'multi-intent-card-clarification'
                      : subIsFallback
                      ? 'multi-intent-card-fallback'
                      : 'multi-intent-card-clear'
                  }`}
                >
                  <div className="multi-intent-card-header">
                    <span className="multi-intent-index-pill">
                      {subIdx + 1}
                    </span>

                    <div className="multi-intent-header-main">
                      {!subIsFallback &&
                      !subNeedsClarification &&
                      sub.matched_question ? (
                        <span className="multi-intent-matched-title">
                          {sub.matched_question}
                        </span>
                      ) : (
                        <span className="multi-intent-matched-title">
                          {sub.query || `Question ${subIdx + 1}`}
                        </span>
                      )}
                    </div>

                    <div className="multi-intent-header-badges">
                      {!subIsFallback &&
                        !subNeedsClarification &&
                        sub.category && (
                          <span className="message-category-badge">
                            <Tag size={10} strokeWidth={2} />
                            {sub.category}
                          </span>
                        )}

                      {!subIsFallback &&
                        !subNeedsClarification &&
                        subSimLabel && (
                          <span
                            className="confidence-pill"
                            title="NLP TF-IDF Cosine Similarity Score"
                          >
                            Similarity: {subSimLabel}
                          </span>
                        )}

                      {subNeedsClarification && (
                        <span className="message-clarification-badge">
                          <GitBranch size={10} strokeWidth={2} />
                          Clarification Needed
                        </span>
                      )}

                      {subIsFallback && (
                        <span className="fallback-pill">
                          <HelpCircle size={11} strokeWidth={2} />
                          <span>No matching FAQ</span>
                        </span>
                      )}
                    </div>
                  </div>

                  {subNeedsClarification ? (
                    <div className="multi-intent-clarification-body">
                      <p className="clarification-message-text">
                        {sub.clarification_message ||
                          'Multiple FAQ topics closely match this part of your question. Please select an option below:'}
                      </p>
                      {subCandidates.length > 0 && (
                        <div
                          className="clarification-candidates-list"
                          role="list"
                          aria-label={`Candidate options for question ${subIdx + 1}`}
                        >
                          {subCandidates.map((candidate, cIdx) => {
                            const candidateSim = formatSimilarityScore(
                              candidate.similarity
                            )
                            return (
                              <button
                                key={`${candidate.faq_id ?? cIdx}-${candidate.question}`}
                                type="button"
                                role="listitem"
                                className="clarification-candidate-btn"
                                disabled={disabled || !onSelectQuestion}
                                onClick={() =>
                                  onSelectQuestion &&
                                  onSelectQuestion(candidate.question)
                                }
                              >
                                <div className="candidate-option-index">
                                  {cIdx + 1}
                                </div>
                                <div className="candidate-option-body">
                                  <span className="candidate-option-question">
                                    {candidate.question}
                                  </span>
                                  <div className="candidate-option-meta">
                                    {candidate.category && (
                                      <span className="candidate-category-tag">
                                        <Tag size={10} strokeWidth={2} />
                                        {candidate.category}
                                      </span>
                                    )}
                                    {candidateSim && (
                                      <span className="candidate-sim-tag">
                                        Similarity: {candidateSim}
                                      </span>
                                    )}
                                  </div>
                                </div>
                                <div
                                  className="candidate-select-cta"
                                  aria-hidden="true"
                                >
                                  <span>Ask</span>
                                  <ArrowUpRight size={14} strokeWidth={2} />
                                </div>
                              </button>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="multi-intent-answer-text">{sub.answer}</div>
                  )}
                </div>
              )
            })}
          </div>
        ) : !isUser && needsClarification ? (
          <div
            className="clarification-card"
            role="region"
            aria-label="Clarification options"
          >
            <div className="clarification-header">
              <div className="clarification-icon-box" aria-hidden="true">
                <HelpCircle size={16} strokeWidth={2} />
              </div>
              <div className="clarification-header-text">
                <span className="clarification-title">
                  Multiple Plausible FAQ Matches
                </span>
                <span className="clarification-subtitle">
                  Select the specific topic you would like answered
                </span>
              </div>
            </div>

            <p className="clarification-message-text">
              {message.clarificationMessage ||
                'Multiple FAQ topics closely match your question. Please select the exact question below:'}
            </p>

            {clarificationCandidates.length > 0 && (
              <div
                className="clarification-candidates-list"
                role="list"
                aria-label="Candidate FAQ options"
              >
                {clarificationCandidates.map((candidate, index) => {
                  const candidateSim = formatSimilarityScore(
                    candidate.similarity
                  )
                  return (
                    <button
                      key={`${candidate.faq_id ?? index}-${candidate.question}`}
                      type="button"
                      role="listitem"
                      className="clarification-candidate-btn"
                      disabled={disabled || !onSelectQuestion}
                      onClick={() =>
                        onSelectQuestion && onSelectQuestion(candidate.question)
                      }
                    >
                      <div className="candidate-option-index">
                        {index + 1}
                      </div>

                      <div className="candidate-option-body">
                        <span className="candidate-option-question">
                          {candidate.question}
                        </span>
                        <div className="candidate-option-meta">
                          {candidate.category && (
                            <span className="candidate-category-tag">
                              <Tag size={10} strokeWidth={2} />
                              {candidate.category}
                            </span>
                          )}
                          {candidateSim && (
                            <span className="candidate-sim-tag">
                              Similarity: {candidateSim}
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="candidate-select-cta" aria-hidden="true">
                        <span>Ask</span>
                        <ArrowUpRight size={14} strokeWidth={2} />
                      </div>
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        ) : (
          <div
            className={`message-bubble ${
              isUser
                ? 'bubble-user'
                : isConnectionError
                ? 'bubble-assistant bubble-error'
                : 'bubble-assistant'
            }`}
          >
            <div className="message-text">{message.text}</div>
            {!isUser &&
              Array.isArray(message.documentSources) &&
              message.documentSources.length > 0 && (
                <div className="doc-sources-box">
                  <div className="doc-sources-title">
                    Sources used
                    {message.sourceConflict && (
                      <span className="doc-conflict-badge">
                        Multiple sources differ
                      </span>
                    )}
                  </div>
                  <ul className="doc-sources-list">
                    {message.documentSources.map((src, sIdx) => {
                      const passageObj =
                        (message.supportingPassages || [])[sIdx] || null
                      const isExpanded = expandedSourceIdx === sIdx
                      const locationText = src.page_number
                        ? `Page ${src.page_number}`
                        : src.section_heading
                        ? src.section_heading
                        : src.paragraph_ref || ''
                      return (
                        <li key={sIdx} className="doc-source-item">
                          <button
                            type="button"
                            className="doc-source-toggle"
                            onClick={() =>
                              setExpandedSourceIdx(isExpanded ? null : sIdx)
                            }
                          >
                            <span>
                              <strong>{src.document_title}</strong>
                              {locationText ? ` — ${locationText}` : ''}
                            </span>
                            <span className="doc-source-action">
                              {isExpanded ? 'Hide passage' : 'View passage'}
                            </span>
                          </button>
                          {isExpanded && passageObj?.passage && (
                            <div className="doc-source-passage">
                              {passageObj.passage}
                            </div>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                </div>
              )}
          </div>
        )}

        {/* Assistant Footer Metadata */}
        {!isUser && (
          <div className="message-footer-meta">
            <div className="message-actions">
              <button
                type="button"
                className={`copy-btn ${copied ? 'copy-btn-active' : ''}`}
                onClick={handleCopy}
                aria-label="Copy assistant response"
                title="Copy response"
              >
                {copied ? (
                  <>
                    <Check size={13} strokeWidth={2.2} />
                    <span>Copied</span>
                  </>
                ) : (
                  <>
                    <Copy size={13} strokeWidth={2} />
                    <span>Copy response</span>
                  </>
                )}
              </button>

              {!isMultiIntent &&
                !isFallback &&
                !needsClarification &&
                similarityLabel && (
                  <span
                    className="confidence-pill"
                    title="NLP TF-IDF Cosine Similarity Score"
                  >
                    Similarity: {similarityLabel}
                  </span>
                )}

              {!isMultiIntent && needsClarification && (
                <span
                  className="clarification-status-pill"
                  title="Ambiguous match — awaiting user selection"
                >
                  Ambiguous Match • {clarificationCandidates.length} options
                </span>
              )}

              {!isMultiIntent && isFallback && !isConnectionError && (
                <span
                  className="fallback-pill"
                  title="Below similarity threshold"
                >
                  <HelpCircle size={12} strokeWidth={2} />
                  <span>No matching FAQ found</span>
                </span>
              )}

              {isMultiIntent && (
                <span
                  className="confidence-pill"
                  title="Independent sub-questions answered"
                >
                  {subResponses.length} questions processed
                </span>
              )}

              {isConnectionError && (
                <span className="error-pill">
                  <AlertCircle size={12} strokeWidth={2} />
                  <span>Backend offline</span>
                </span>
              )}
            </div>

            {!isMultiIntent &&
              !isFallback &&
              !needsClarification &&
              message.matchedQuestion && (
                <div className="matched-question-caption">
                  <span className="matched-question-label">Matched FAQ:</span>{' '}
                  <span>{message.matchedQuestion}</span>
                </div>
              )}
          </div>
        )}

        {/* Smart Follow-Up Suggestions (only after clear_match responses) */}
        {followUpSuggestions.length > 0 && (
          <div
            className="followup-suggestions-block"
            aria-label="Related follow-up questions"
          >
            <div className="followup-suggestions-header">
              <Sparkles size={12} strokeWidth={2} />
              <span>
                Related in {message.category || 'Knowledge Base'}
              </span>
            </div>

            <div className="followup-suggestions-list">
              {followUpSuggestions.map((item) => (
                <button
                  key={`${item.id ?? item.question}`}
                  type="button"
                  className="followup-chip"
                  disabled={disabled || !onSelectQuestion}
                  onClick={() =>
                    onSelectQuestion && onSelectQuestion(item.question)
                  }
                  title={`Ask follow-up: "${item.question}"`}
                >
                  <CornerDownRight
                    size={13}
                    strokeWidth={2}
                    className="followup-chip-icon"
                  />
                  <span className="followup-chip-text">{item.question}</span>
                  <ArrowUpRight
                    size={13}
                    strokeWidth={2}
                    className="followup-chip-arrow"
                  />
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default MessageBubble
