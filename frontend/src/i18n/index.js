/** Translations for the health officer pages: ``t(key, values)`` in the chosen language, English as fallback. */
import en from './en'

const MESSAGES = { en }

/** Languages offered in the language switch (more are added with their message files). */
export const LANGUAGES = [{ code: 'en', label: 'English' }]

const STORAGE_KEY = 'privafuse.language'

export function currentLanguage() {
  const stored = typeof localStorage !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null
  return stored && MESSAGES[stored] ? stored : 'en'
}

export function setLanguage(code) {
  if (MESSAGES[code]) localStorage.setItem(STORAGE_KEY, code)
}

export function translate(language, key, values = {}) {
  const template = MESSAGES[language]?.[key] ?? en[key] ?? key
  return template.replace(/\{(\w+)\}/g, (_, name) => (values[name] === undefined || values[name] === null ? '' : String(values[name])))
}

/** The message files, for checks that every language has every key. */
export const messageFiles = MESSAGES
