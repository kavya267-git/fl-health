/** Mark: one coordinator node linked to four hospital nodes. */
export function LogoMark({ className = 'h-8 w-8' }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <rect width="32" height="32" rx="7" fill="#2d59b5" />
      <g fill="none" stroke="#ecf2fc" strokeWidth="1.6" strokeLinecap="round">
        <path d="M16 16 8 9M16 16l8-7M16 16l-8 8M16 16l8 8" />
      </g>
      <circle cx="16" cy="16" r="3.6" fill="#b6cdf2" />
      <g fill="#ecf2fc">
        <circle cx="8" cy="9" r="2.2" />
        <circle cx="24" cy="9" r="2.2" />
        <circle cx="8" cy="24" r="2.2" />
        <circle cx="24" cy="24" r="2.2" />
      </g>
    </svg>
  )
}

export function Logo({ light = false }) {
  return (
    <div className="flex items-center gap-2.5">
      <LogoMark />
      <div className="leading-tight">
        <p className={`text-[15px] font-semibold ${light ? 'text-white' : 'text-ink'}`}>PrivaFuse</p>
        <p className={`text-[11px] ${light ? 'text-brand-200' : 'text-muted'}`}>Collaborative healthcare intelligence</p>
      </div>
    </div>
  )
}
