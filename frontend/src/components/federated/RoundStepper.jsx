import { ROUND_STEPS } from '../../utils/constants'
import { classNames } from '../../utils/format'

/** The round lifecycle as an ordered list. These really are sequential steps. */
export function RoundStepper({ status }) {
  const failed = status === 'FAILED'
  const currentIndex = ROUND_STEPS.findIndex((step) => step.status === status)
  return (
    <ol className="flex flex-wrap gap-x-1 gap-y-2" aria-label="Round status">
      {ROUND_STEPS.map((step, index) => {
        const done = !failed && (index < currentIndex || status === 'COMPLETED')
        const current = !failed && index === currentIndex && status !== 'COMPLETED'
        return (
          <li key={step.status} className="flex items-center gap-1" aria-current={current ? 'step' : undefined}>
            <span
              className={classNames(
                'rounded-full px-2.5 py-1 text-xs font-medium',
                step.status === 'COMPLETED' && status === 'COMPLETED'
                  ? 'bg-ok text-white'
                  : done
                    ? 'bg-brand-50 text-brand-700'
                    : current
                      ? 'bg-brand-700 text-white'
                      : 'bg-canvas text-faint',
              )}
            >
              {step.label}
            </span>
            {index < ROUND_STEPS.length - 1 ? <span className="h-px w-3 bg-line-strong" aria-hidden="true" /> : null}
          </li>
        )
      })}
      {failed ? (
        <li>
          <span className="rounded-full bg-alert px-2.5 py-1 text-xs font-medium text-white">Failed</span>
        </li>
      ) : null}
    </ol>
  )
}
