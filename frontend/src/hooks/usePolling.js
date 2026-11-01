import { useEffect, useRef } from 'react'

/** Calls `callback` every `intervalMs` while `active` is true. */
export function usePolling(callback, intervalMs, active) {
  const saved = useRef(callback)
  saved.current = callback

  useEffect(() => {
    if (!active) return undefined
    const timer = setInterval(() => saved.current(), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs, active])
}
