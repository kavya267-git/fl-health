/**
 * Supabase Auth client (browser side).
 *
 * Only the project URL and the *anon* key are used here. The service-role key
 * stays on the backend and must never be added to a VITE_ variable.
 */
import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

export const isSupabaseConfigured = Boolean(url && anonKey)

let client = null

export function getSupabase() {
  if (!isSupabaseConfigured) return null
  if (!client) {
    client = createClient(url, anonKey, { auth: { persistSession: true, autoRefreshToken: true } })
  }
  return client
}
