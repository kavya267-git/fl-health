/** Every API call the app makes. Components never build URLs themselves. */
import { expectShape, http } from './api'

const get = async (url, params, shape, what) => expectShape((await http.get(url, { params })).data, shape, what)
const post = async (url, body, shape, what) => expectShape((await http.post(url, body)).data, shape, what)

const ROUND_KEYS = ['id', 'modality', 'status', 'participants']

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
  setUserRole: (id, role, hospitalId = null) =>
    post(`/api/users/${encodeURIComponent(id)}/role`, { role, hospital_id: hospitalId }, { keys: ['id', 'role'] }, 'user'),

  // Hospitals
  hospitals: () => get('/api/hospitals', undefined, { array: true }, 'hospital list'),
  hospital: (id) => get(`/api/hospitals/${encodeURIComponent(id)}`, undefined, { keys: ['id', 'name', 'online'] }, 'hospital'),
  myHospital: () => get('/api/my-hospital', undefined, { keys: ['hospital', 'metrics'] }, 'your hospital'),
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
