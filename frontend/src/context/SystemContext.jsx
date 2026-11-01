import { createContext, useContext, useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import { api } from '../services/endpoints'

const SystemContext = createContext(null)

/** Public server configuration: mode, auth provider and which model backends are active. */
export function SystemProvider({ children }) {
  const state = useApi(() => api.systemConfig(), [])
  const value = useMemo(
    () => ({ status: state.status, config: state.data, error: state.error, reload: state.reload }),
    [state.status, state.data, state.error, state.reload],
  )
  return <SystemContext.Provider value={value}>{children}</SystemContext.Provider>
}

export function useSystem() {
  const value = useContext(SystemContext)
  if (!value) throw new Error('useSystem must be used inside <SystemProvider>')
  return value
}
