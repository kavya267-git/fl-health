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
}

export const ROLE_LABELS = { admin: 'Administrator', coordinator: 'FL coordinator', viewer: 'Viewer' }
export const ROLE_ORDER = ['viewer', 'coordinator', 'admin']
export const ROLE_DESCRIPTIONS = {
  viewer: 'Read-only: dashboards, models, surveillance, forecasts and explanations.',
  coordinator: 'Everything a viewer can do, plus running rounds, hospital availability and the audit log.',
  admin: 'Everything a coordinator can do, plus managing users and their roles.',
}
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

export const canManageRounds =(user) => Boolean(user) && ['admin', 'coordinator'].includes(user.role)
