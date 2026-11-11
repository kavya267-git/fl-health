/** Every API call the app makes. Components never build URLs themselves. */
import { expectShape, http } from './api'

const get = async (url, params, shape, what) => expectShape((await http.get(url, { params })).data, shape, what)
const post = async (url, body, shape, what) => expectShape((await http.post(url, body)).data, shape, what)

const ROUND_KEYS = ['id', 'modality', 'status', 'participants']

/** Downloads a file through the signed-in API client and hands it to the browser as a file. */
async function download(url, fallbackName) {
  const response = await http.get(url, { responseType: 'blob' })
  const disposition = response.headers?.['content-disposition'] || ''
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] || fallbackName
  const link = document.createElement('a')
  link.href = URL.createObjectURL(response.data)
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(link.href)
  return name
}

export const api = {
  // System and auth
  systemConfig: () => get('/api/system/config', undefined, { keys: ['demo_mode', 'auth_provider', 'model_backends'] }, 'configuration'),
  me: () => get('/api/auth/me', undefined, { keys: ['email', 'role'] }, 'user profile'),
  demoLogin: (email, password) => post('/api/auth/demo-login', { email, password }, { keys: ['access_token', 'user'] }, 'sign-in response'),
  register: (email, password, displayName) =>
    post(
      '/api/auth/register',
      { email, password, display_name: displayName || null },
      { keys: ['access_token', 'user'] },
      'sign-up response',
    ),
  recordSession: () => post('/api/auth/session', {}, { keys: ['user'] }, 'session response'),

  // Users (administrators only)
  users: () => get('/api/users', undefined, { array: true }, 'user list'),
  setUserRole: (id, role, hospitalId = null, jurisdiction = null) =>
    post(
      `/api/users/${encodeURIComponent(id)}/role`,
      { role, hospital_id: hospitalId, jurisdiction },
      { keys: ['id', 'role'] },
      'user',
    ),

  // Health officer
  situation: () => get('/api/officer/situation', undefined, { keys: ['diseases', 'about_forecast', 'data_status'] }, 'situation report'),
  forecastStatus: () => get('/api/officer/forecast-status', undefined, { keys: ['available'] }, 'forecast status'),
  downloadSituation: (format) => download(`/api/officer/situation.${format}`, `situation-report.${format}`),
  alerts: (state) => get('/api/alerts', state ? { state } : undefined, { array: true }, 'alerts'),
  acknowledgeAlert: (id) => post(`/api/alerts/${encodeURIComponent(id)}/acknowledge`, {}, { keys: ['id', 'state'] }, 'alert'),
  recordAlertOutcome: (id, outcome, note) =>
    post(`/api/alerts/${encodeURIComponent(id)}/outcome`, { outcome, note }, { keys: ['id', 'state'] }, 'alert'),

  // Resource planning
  planning: (hospitalId) => get('/api/planning', hospitalId ? { hospital_id: hospitalId } : undefined, { keys: ['available', 'hospital'] }, 'resource plan'),
  setCapacity: (body) => post('/api/planning/capacity', body, { keys: ['total_beds'] }, 'capacity'),
  planningAssumptions: () => get('/api/planning/assumptions', undefined, { array: true }, 'assumptions'),
  setPlanningAssumptions: (disease, body) =>
    post(`/api/planning/assumptions/${encodeURIComponent(disease)}`, body, { keys: ['disease'] }, 'assumptions'),

  // Hospitals
  hospitals: () => get('/api/hospitals', undefined, { array: true }, 'hospital list'),
  hospital: (id) => get(`/api/hospitals/${encodeURIComponent(id)}`, undefined, { keys: ['id', 'name', 'online'] }, 'hospital'),
  myHospital: () => get('/api/my-hospital', undefined, { keys: ['hospital', 'metrics'] }, 'your hospital'),
  generateNodeToken: () => post('/api/my-hospital/node-token', {}, { keys: ['token', 'hospital_id'] }, 'node token'),
  downloadDataTemplate: () => download('/api/my-hospital/data-template.zip', 'medifed-data-template.zip'),

  // Hospital registration: the public form (no sign-in) and the administrators' review
  registrationRegions: () => get('/api/registrations/regions', undefined, { array: true }, 'region list'),
  submitRegistration: (body) => post('/api/registrations', body, { keys: ['id', 'status'] }, 'registration receipt'),
  registrations: (status) => get('/api/registrations', status ? { status } : undefined, { array: true }, 'hospital requests'),
  pendingRegistrations: () => get('/api/registrations/pending-count', undefined, { keys: ['pending'] }, 'pending count'),
  approveRegistration: (id) => post(`/api/registrations/${encodeURIComponent(id)}/approve`, {}, { keys: ['id', 'status'] }, 'request'),
  rejectRegistration: (id, reason) =>
    post(`/api/registrations/${encodeURIComponent(id)}/reject`, { reason }, { keys: ['id', 'status'] }, 'request'),
  revokeRegistration: (id, reason) =>
    post(`/api/registrations/${encodeURIComponent(id)}/revoke`, { reason }, { keys: ['id', 'status'] }, 'request'),
  setHospitalParticipation: (id, participating) =>
    post(`/api/hospitals/${encodeURIComponent(id)}/participation`, { participating }, { keys: ['id', 'participating'] }, 'hospital'),
  hospitalMetrics: (id) =>
    get(`/api/hospitals/${encodeURIComponent(id)}/metrics`, undefined, { keys: ['participation'] }, 'hospital metrics'),
  setHospitalAvailability: (id, online) =>
    post(`/api/hospitals/${encodeURIComponent(id)}/availability`, { online }, { keys: ['id', 'online'] }, 'hospital'),

  // Federated learning
  rounds: (modality) => get('/api/federated/rounds', modality ? { modality } : undefined, { array: true }, 'round list'),
  round: (id) => get(`/api/federated/rounds/${encodeURIComponent(id)}`, undefined, { keys: ROUND_KEYS }, 'round'),
  roundMetrics: (id) => get(`/api/federated/rounds/${encodeURIComponent(id)}/metrics`, undefined, { keys: ['local'] }, 'round metrics'),
  startRound: (body) => post('/api/federated/rounds/start', body, { keys: ROUND_KEYS }, 'round'),
  aggregateRound: (id) => post(`/api/federated/rounds/${encodeURIComponent(id)}/aggregate`, {}, { keys: ROUND_KEYS }, 'round'),
  cancelRound: (id) => post(`/api/federated/rounds/${encodeURIComponent(id)}/cancel`, {}, { keys: ROUND_KEYS }, 'round'),

  // Models
  models: () => get('/api/models', undefined, { array: true }, 'model list'),
  model: (id) => get(`/api/models/${encodeURIComponent(id)}`, undefined, { keys: ['id', 'versions', 'task'] }, 'model'),
  modelMetrics: (id) => get(`/api/models/${encodeURIComponent(id)}/metrics`, undefined, { keys: ['series', 'task'] }, 'model metrics'),

  // Analytics
  overview: () => get('/api/analytics/overview', undefined, { keys: ['kpis', 'models', 'hospitals', 'data_status'] }, 'dashboard summary'),
  analyticsOptions: () => get('/api/analytics/options', undefined, { keys: ['diseases', 'regions', 'periods'] }, 'analytics options'),
  hotspots: (disease, period) =>
    get('/api/analytics/hotspots', { disease, period }, { keys: ['regions', 'geojson', 'summary', 'time_period'] }, 'surveillance result'),
  forecast: (regionId, disease, horizon) =>
    get('/api/analytics/forecast', { region_id: regionId, disease, horizon }, { keys: ['available', 'history', 'disclaimer'] }, 'forecast'),
  explainability: (modality, scope, caseId) =>
    get('/api/analytics/explainability', { modality, scope, case_id: caseId }, { keys: ['available', 'cases', 'scope'] }, 'explanation'),
  privacy: () => get('/api/analytics/privacy', undefined, { keys: ['checks', 'statement', 'differential_privacy'] }, 'privacy report'),

  // Audit
  audit: (params) => get('/api/audit', params, { keys: ['items', 'total'] }, 'audit log'),
  verifyAudit: () => get('/api/audit/verify', undefined, { keys: ['valid', 'entries_checked'] }, 'audit verification'),
}
