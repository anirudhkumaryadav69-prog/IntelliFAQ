import {
  GraduationCap,
  CreditCard,
  CalendarCheck,
  FileSpreadsheet,
  ArrowUpRight,
} from 'lucide-react'

const SUGGESTED_ITEMS = [
  {
    id: 'admission',
    category: 'Admissions',
    title: 'Admission requirements',
    prompt: 'What are the admission requirements for undergraduate programs?',
    description: 'Eligibility criteria, entrance tests & application documents',
    icon: GraduationCap,
  },
  {
    id: 'fees',
    category: 'Fee Payment',
    title: 'Fee payment',
    prompt: 'How do I pay my semester tuition fees and what are the deadlines?',
    description: 'Payment modes, installment policies & receipt generation',
    icon: CreditCard,
  },
  {
    id: 'attendance',
    category: 'Attendance',
    title: 'Attendance policy',
    prompt: 'What is the minimum attendance policy required for appearing in exams?',
    description: 'Minimum criteria, medical leave & condonation guidelines',
    icon: CalendarCheck,
  },
  {
    id: 'exams',
    category: 'Examinations',
    title: 'Examination schedule',
    prompt: 'Where can I check the upcoming semester examination schedule?',
    description: 'Mid-term dates, final exam timetable & hall ticket release',
    icon: FileSpreadsheet,
  },
]

function SuggestedQuestions({ onSelectQuestion, disabled }) {
  return (
    <div className="suggested-section" aria-label="Suggested FAQ topics">
      <div className="suggested-header-row">
        <span className="suggested-label">Suggested Institutional Inquiries</span>
        <span className="suggested-sub-hint">Click any card to ask immediately</span>
      </div>
      <div className="suggested-grid">
        {SUGGESTED_ITEMS.map((item) => {
          const IconComponent = item.icon
          return (
            <button
              key={item.id}
              type="button"
              className="suggested-card"
              onClick={() => onSelectQuestion(item.prompt)}
              disabled={disabled}
            >
              <div className="suggested-card-top">
                <div className="suggested-icon-group">
                  <div className="suggested-icon-wrap">
                    <IconComponent size={18} strokeWidth={2} />
                  </div>
                  <span className="suggested-category-tag">{item.category}</span>
                </div>
                <ArrowUpRight
                  size={16}
                  className="suggested-arrow"
                  aria-hidden="true"
                />
              </div>
              <div className="suggested-card-body">
                <h3 className="suggested-title">{item.title}</h3>
                <p className="suggested-desc">{item.description}</p>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

export default SuggestedQuestions
