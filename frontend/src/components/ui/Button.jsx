import { LoaderCircle } from 'lucide-react'
import { classNames } from '../../utils/format'

const VARIANTS = {
  primary: 'bg-brand-700 text-white hover:bg-brand-800 disabled:bg-brand-700/50',
  secondary: 'border border-line-strong bg-surface text-ink hover:bg-canvas disabled:text-faint',
  danger: 'border border-alert/30 bg-surface text-alert hover:bg-alert-soft disabled:text-faint',
  ghost: 'text-brand-700 hover:bg-brand-50 disabled:text-faint',
}

const SIZES = { md: 'h-10 px-4 text-sm', sm: 'h-8 px-3 text-[13px]' }

export function Button({
  children,
  variant = 'secondary',
  size = 'md',
  loading = false,
  icon: Icon,
  className = '',
  type = 'button',
  disabled,
  ...rest
}) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={classNames(
        'inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors',
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading ? (
        <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
      ) : Icon ? (
        <Icon className="h-4 w-4" aria-hidden="true" />
      ) : null}
      {children}
    </button>
  )
}
