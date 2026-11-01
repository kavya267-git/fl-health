import { Info, X } from 'lucide-react'
import { useEffect, useId, useRef } from 'react'
import { classNames } from '../../utils/format'

export function PageHeader({ title, description, actions }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        {description ? <p className="mt-1.5 max-w-3xl text-[15px] leading-relaxed text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  )
}

/** One headline number with its label and an optional line of context. */
export function Stat({ label, value, detail, icon: Icon }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-5 py-4 shadow-card">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted">{label}</p>
        {Icon ? <Icon className="h-4 w-4 text-faint" aria-hidden="true" /> : null}
      </div>
      <p className="mt-2 text-3xl font-semibold leading-none tracking-tight text-ink">{value}</p>
      {detail ? <p className="mt-2 text-[13px] leading-snug text-muted">{detail}</p> : null}
    </div>
  )
}

const COLUMN_CLASSES = { 2: 'sm:grid-cols-2', 3: 'sm:grid-cols-3', 5: 'grid-cols-2 sm:grid-cols-3 xl:grid-cols-5' }

export function DefinitionList({ items, columns = 2 }) {
  return (
    <dl className={classNames('grid gap-x-6 gap-y-3', COLUMN_CLASSES[columns] || '')}>
      {items.map(({ term, value }) => (
        <div key={term} className="min-w-0">
          <dt className="text-xs text-muted">{term}</dt>
          <dd className="mt-0.5 break-words text-sm font-medium text-ink">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

const NOTE_TONES = {
  info: 'border-brand-100 bg-brand-50 text-brand-900',
  warn: 'border-warn/30 bg-warn-soft text-ink',
  alert: 'border-alert/25 bg-alert-soft text-ink',
  ok: 'border-ok/25 bg-ok-soft text-ink',
}

export function Note({ tone = 'info', title, children, className = '' }) {
  return (
    <div
      role={tone === 'alert' ? 'alert' : undefined}
      className={classNames('flex gap-3 rounded-md border px-4 py-3 text-sm leading-relaxed', NOTE_TONES[tone], className)}
    >
      <Info className="mt-0.5 h-4 w-4 shrink-0 opacity-70" aria-hidden="true" />
      <div className="min-w-0">
        {title ? <p className="font-semibold">{title}</p> : null}
        <div className={title ? 'mt-0.5' : ''}>{children}</div>
      </div>
    </div>
  )
}

export function Field({ label, hint, children, htmlFor }) {
  return (
    <div>
      <label htmlFor={htmlFor} className="block text-sm font-medium text-ink">
        {label}
      </label>
      <div className="mt-1.5">{children}</div>
      {hint ? <p className="mt-1 text-xs leading-snug text-muted">{hint}</p> : null}
    </div>
  )
}

export const inputClass =
  'block h-10 w-full rounded-md border border-line-strong bg-surface px-3 text-sm text-ink placeholder:text-faint ' +
  'focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-100 disabled:bg-canvas disabled:text-faint'

export function Select({ value, onChange, options, id, className = '', ...rest }) {
  return (
    <select
      id={id}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className={classNames(inputClass, className)}
      {...rest}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  )
}

/** Segmented control for a small set of mutually exclusive views. */
export function Tabs({ value, onChange, options, label }) {
  return (
    <div role="tablist" aria-label={label} className="inline-flex rounded-md border border-line-strong bg-surface p-0.5">
      {options.map((option) => {
        const selected = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(option.value)}
            className={classNames(
              'rounded px-3.5 py-1.5 text-sm font-medium transition-colors',
              selected ? 'bg-brand-700 text-white' : 'text-muted hover:text-ink',
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

export function Modal({ title, onClose, children, footer }) {
  const titleId = useId()
  const panel = useRef(null)

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    panel.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-[1100] flex items-start justify-center overflow-y-auto bg-brand-950/45 px-4 py-10">
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="w-full max-w-xl rounded-lg bg-surface shadow-raised focus:outline-none"
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <h2 id={titleId} className="text-base font-semibold text-ink">
            {title}
          </h2>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded p-1 text-muted hover:bg-canvas hover:text-ink">
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
        <div className="px-5 py-5">{children}</div>
        {footer ? <div className="flex justify-end gap-2 border-t border-line px-5 py-4">{footer}</div> : null}
      </div>
    </div>
  )
}

export function Th({ children, align = 'left', className = '' }) {
  return (
    <th
      scope="col"
      className={classNames(
        'whitespace-nowrap border-b border-line bg-canvas px-4 py-2.5 text-xs font-semibold text-muted',
        align === 'right' ? 'text-right' : 'text-left',
        className,
      )}
    >
      {children}
    </th>
  )
}

export function Td({ children, align = 'left', className = '', ...rest }) {
  return (
    <td
      className={classNames('border-b border-line px-4 py-2.5 text-sm text-ink', align === 'right' ? 'text-right' : 'text-left', className)}
      {...rest}
    >
      {children}
    </td>
  )
}
