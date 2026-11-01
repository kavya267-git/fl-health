import { classNames } from '../../utils/format'

export function Card({ children, className = '', as: Tag = 'section', ...rest }) {
  return (
    <Tag className={classNames('rounded-lg border border-line bg-surface shadow-card', className)} {...rest}>
      {children}
    </Tag>
  )
}

export function CardHeader({ title, description, action, className = '' }) {
  return (
    <div className={classNames('flex items-start justify-between gap-4 border-b border-line px-5 py-4', className)}>
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold leading-snug text-ink">{title}</h2>
        {description ? <p className="mt-1 text-sm leading-snug text-muted">{description}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  )
}

export function CardBody({ children, className = '' }) {
  return <div className={classNames('px-5 py-4', className)}>{children}</div>
}
