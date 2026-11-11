/** Labels and colours used in more than one place. */

export const MODALITIES = {
  ehr: { id: 'ehr', label: 'EHR', name: 'Electronic health records', target: 'TabNet', color: '#4353b3', soft: 'bg-ehr-soft text-ehr' },
  ecg: { id: 'ecg', label: 'ECG', name: 'Electrocardiogram', target: 'CNN-BiLSTM', color: '#b03a60', soft: 'bg-ecg-soft text-ecg' },
  xray: { id: 'xray', label: 'X-ray', name: 'Chest X-ray', target: 'EfficientNet-B3', color: '#2a7b99', soft: 'bg-xray-soft text-xray' },
}
export const MODALITY_ORDER = ['ehr', 'ecg', 'xray']

/** The round lifecycle, in order. FAILED can follow any step. */
export const ROUND_STEPS = [
  { status: 'CREATED', label: 'Created' },
  { status: 'WAITING_FOR_CLIENTS', label: 'Waiting for hospitals' },
  { status: 'TRAINING', label: 'Local training' },
  { status: 'UPDATES_RECEIVING', label: 'Receiving updates' },
  { status: 'AGGREGATING', label: 'Aggregating (FedAvg)' },
  { status: 'EVALUATING', label: 'Evaluating' },
  { status: 'COMPLETED', label: 'Completed' },
]
export const ROUND_STATUS_LABELS = Object.fromEntries([...ROUND_STEPS.map((s) => [s.status, s.label]), ['FAILED', 'Failed']])
export const ACTIVE_ROUND_STATUSES = ['CREATED', 'WAITING_FOR_CLIENTS', 'TRAINING', 'UPDATES_RECEIVING', 'AGGREGATING', 'EVALUATING']
export const isRoundActive = (round) => Boolean(round) && ACTIVE_ROUND_STATUSES.includes(round.status)

export const PARTICIPANT_LABELS = {
  INVITED: 'Invited',
  JOINED: 'Joined',
  TRAINING: 'Training locally',
  UPDATE_SUBMITTED: 'Update sent',
  UPDATE_REJECTED: 'Update rejected',
  EVALUATED: 'Evaluated',
  EVALUATION_FAILED: 'Evaluation failed',
  DROPPED: 'Dropped',
  FAILED: 'Failed',
}

/** Surveillance statuses. A flagged region is a candidate for review, never a confirmed outbreak. */
export const HOTSPOT_STATUS = {
  CANDIDATE_HOTSPOT: { label: 'Potential hotspot', color: '#b3261e', tone: 'alert' },
  ELEVATED: { label: 'Elevated', color: '#a4680e', tone: 'warn' },
  NORMAL: { label: 'Normal', color: '#2a7a57', tone: 'ok' },
  INSUFFICIENT_DATA: { label: 'Insufficient data', color: '#84918d', tone: 'nodata' },
}
export const HOTSPOT_ORDER = ['CANDIDATE_HOTSPOT', 'ELEVATED', 'NORMAL', 'INSUFFICIENT_DATA']

export const METRIC_LABELS = { accuracy: 'Accuracy', precision: 'Precision', recall: 'Recall', f1: 'F1', loss: 'Loss' }

export const AUDIT_ACTION_LABELS = {
  USER_LOGIN: 'User signed in',
  USER_REGISTERED: 'Account created',
  USER_ROLE_CHANGED: 'User role changed',
  FL_ROUND_CREATED: 'Round created',
  HOSPITAL_JOINED_ROUND: 'Hospital joined round',
  LOCAL_UPDATE_RECEIVED: 'Local update received',
  AGGREGATION_STARTED: 'Aggregation started',
  AGGREGATION_COMPLETED: 'Aggregation completed',
  GLOBAL_MODEL_CREATED: 'Global model created',
  FL_ROUND_COMPLETED: 'Round completed',
  FL_ROUND_FAILED: 'Round failed',
  ANALYTICS_GENERATED: 'Analytics generated',
  FORECAST_GENERATED: 'Forecast generated',
  MODEL_ACCESSED: 'Model accessed',
  HOSPITAL_STATUS_CHANGED: 'Hospital availability changed',
  NODE_CONNECTED: 'Hospital node connected',
  HOSPITAL_DROPPED: 'Hospital dropped from round',
  HOSPITAL_PARTICIPATION_CHANGED: 'Hospital participation changed',
  HOSPITAL_DECLINED_ROUND: 'Hospital declined a round',
  ALERT_CREATED: 'Alert created',
  ALERT_ACKNOWLEDGED: 'Alert acknowledged',
  ALERT_OUTCOME_RECORDED: 'Alert outcome recorded',
  SITUATION_REPORT_EXPORTED: 'Situation report exported',
  HOSPITAL_CAPACITY_CHANGED: 'Hospital capacity changed',
  PLANNING_ASSUMPTIONS_CHANGED: 'Planning assumptions changed',
  UPDATE_FLAGGED_UNUSUAL: 'Unusual model update flagged',
  HOSPITAL_REGISTRATION_SUBMITTED: 'Hospital registration submitted',
  HOSPITAL_REGISTRATION_APPROVED: 'Hospital registration approved',
  HOSPITAL_REGISTRATION_REJECTED: 'Hospital registration rejected',
  HOSPITAL_REGISTRATION_REVOKED: 'Hospital access revoked',
  NODE_TOKEN_ISSUED: 'Node token issued',
  NODE_DATA_CHECK_REPORTED: 'Node data check reported',
}

export const ROLE_LABELS = {
  admin: 'Administrator',
  coordinator: 'FL coordinator',
  viewer: 'Viewer',
  hospital: 'Hospital operator',
  hospital_manager: 'Hospital manager',
  health_officer: 'Health officer',
  researcher: 'Researcher',
}
export const ROLE_ORDER = ['viewer', 'researcher', 'health_officer', 'hospital_manager', 'hospital', 'coordinator', 'admin']
export const ROLE_DESCRIPTIONS = {
  viewer: 'Read-only: dashboards, models, surveillance, forecasts and explanations.',
  researcher: "Read-only, like a viewer, but without any single hospital's detail pages.",
  health_officer: 'Surveillance and forecasts for the regions in their jurisdiction only. No federation or hospital pages.',
  hospital_manager:
    "Works for one hospital: the general dashboards plus that hospital's own page. Cannot change its participation in rounds.",
  hospital:
    "Works for one hospital: sees the general dashboards like a viewer, plus that hospital's own page, node and participation switch. No other hospital's details.",
  coordinator: 'Everything a viewer can do, plus running rounds, hospital availability and the audit log.',
  admin: 'Everything a coordinator can do, plus managing users and their roles.',
}
/** Roles linked to one hospital (user.hospital_id); must match HOSPITAL_ROLES on the server. */
export const HOSPITAL_ROLES = ['hospital', 'hospital_manager']
/** Roles limited to a jurisdiction (user.jurisdiction, region ids); must match JURISDICTION_ROLES on the server. */
export const JURISDICTION_ROLES = ['health_officer']
/** Must match MIN_PASSWORD_LENGTH on the server, which is what actually enforces it. */
export const MIN_PASSWORD_LENGTH = 8
/**
 * How to describe a hospital's availability. In-process hospitals are simulated and toggled online/offline;
 * external hospitals are nodes on their own machines, connected while their heartbeat keeps arriving.
 */
export function availabilityLabel(hospital) {
  if (hospital.node_mode !== 'external') return hospital.online ? 'Online' : 'Offline'
  if (hospital.online) return 'Connected'
  return hospital.node ? 'Disconnected' : 'Never connected'
}

/** Hospital operators and managers act for one hospital (user.hospital_id). */
export const isHospitalOperator = (user) => Boolean(user) && HOSPITAL_ROLES.includes(user.role)
export const isHealthOfficer = (user) => Boolean(user) && JURISDICTION_ROLES.includes(user.role)
/** Only the hospital's operator (not its manager) switches its participation in rounds. */
export const canChangeParticipation = (user) => Boolean(user) && user.role === 'hospital'
/** Hospital detail pages: not for health officers or researchers; the server enforces the same rule. */
export const canOpenHospitalDetails = (user) => Boolean(user) && !['health_officer', 'researcher'].includes(user.role)
/** Where a user lands after signing in. */
export const homePathFor = (user) =>
  user?.role === 'hospital_manager' ? '/planning' : isHospitalOperator(user) ? '/my-hospital' : isHealthOfficer(user) ? '/situation' : '/'
/** Situation report and alerts: administrators, coordinators and health officers (the server enforces it). */
export const canSeeOfficerViews = (user) => Boolean(user) && ['admin', 'coordinator', 'health_officer'].includes(user.role)
/** The audit log is for coordinators and administrators; the server enforces the same rule. */
export const canSeeAudit = (user) => Boolean(user) && ['admin', 'coordinator'].includes(user.role)

export const canManageRounds = (user) => Boolean(user) && ['admin', 'coordinator'].includes(user.role)

/**
 * How forecast intervals are named on screen. They come from the model's past errors and, in the backtest,
 * covered fewer weeks than their nominal level (RESULTS.md Part C), so the label says so.
 */
export const LIKELY_RANGE_NOTE = 'Likely range (based on past errors; often too narrow)'

/** Where hospitals download the agent: the agent-v1.0.1 GitHub Release asset (override with VITE_AGENT_DOWNLOAD_URL). */
export const AGENT_DOWNLOAD_URL =
  import.meta.env.VITE_AGENT_DOWNLOAD_URL ||
  'https://github.com/kavya267-git/medi-fed/releases/download/agent-v1.0.1/MediFed-Hospital-Agent-Windows.zip'

/** Which F1 a modality reports (as the server computes it: ml/evaluation/metrics.py). */
export const F1_KIND = {
  ehr: { short: 'adverse outcome', full: 'F1 of the positive class (adverse outcome), at the 0.5 threshold' },
  xray: { short: 'finding present', full: 'F1 of the positive class (finding present), at the 0.5 threshold' },
  ecg: { short: 'macro average', full: 'F1 averaged over the four heartbeat classes (macro average)' },
}
