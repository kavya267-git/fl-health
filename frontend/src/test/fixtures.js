/** Response fixtures shaped like the API's real responses. */

export const systemConfig = {
  app_name: 'FL-Healthcare',
  version: '1.0.0',
  demo_mode: true,
  simulated_label: 'SIMULATED / DEMONSTRATION DATA',
  auth_provider: 'demo',
  demo_accounts: [{ email: 'admin@fl-healthcare.demo', role: 'admin', display_name: 'Demo Administrator' }],
  signup_enabled: true,
  hospital_nodes: 'in-process',
  database: 'sqlite',
  pytorch_available: true,
  model_backends: {
    ehr: { architecture: 'TabNet', backend: 'pytorch', target_architecture: 'TabNet', is_target_architecture: true },
    ecg: { architecture: 'CNN-BiLSTM', backend: 'pytorch', target_architecture: 'CNN-BiLSTM', is_target_architecture: true },
    xray: { architecture: 'EfficientNet-B3', backend: 'pytorch', target_architecture: 'EfficientNet-B3', is_target_architecture: true },
  },
  modalities: ['ehr', 'ecg', 'xray'],
}

export const adminUser = {
  id: 'demo-admin',
  email: 'admin@fl-healthcare.demo',
  display_name: 'Demo Administrator',
  role: 'admin',
  hospital_id: null,
  provider: 'demo',
}

/** A user who created their own account through the sign-up form. */
export const signedUpUser = {
  id: 'local-1',
  email: 'priya@example.org',
  display_name: 'Priya N',
  role: 'viewer',
  hospital_id: null,
  provider: 'demo',
}

/** GET /api/users as an administrator sees it. */
export const managedUsers = [
  {
    ...adminUser,
    created_at: '2026-01-05T09:00:00+00:00',
    last_login_at: '2026-01-06T09:00:00+00:00',
    built_in: true,
    role_locked: true,
    role_locked_reason: 'Built-in demo accounts keep their role.',
  },
  {
    ...signedUpUser,
    created_at: '2026-01-06T10:00:00+00:00',
    last_login_at: null,
    built_in: false,
    role_locked: false,
    role_locked_reason: null,
  },
]

export const viewerUser = {
  ...adminUser,
  id: 'demo-viewer',
  email: 'viewer@fl-healthcare.demo',
  display_name: 'Demo Analyst',
  role: 'viewer',
}

const hospital = (id, name) => ({
  id,
  name,
  kind: 'Teaching hospital',
  online: true,
  modalities: ['ehr', 'ecg', 'xray'],
  data_summary: { ehr: { source: 'simulated', simulated: true, train_samples: 900, val_samples: 300 } },
  is_simulated: true,
  last_activity_at: null,
  current_round: null,
  latest_update: null,
  rounds_completed: 0,
  fl_participation: 'IDLE',
})

export const hospitals = [
  hospital('hospital_a', 'Northfield General Hospital'),
  hospital('hospital_b', 'Riverside Medical Centre'),
  hospital('hospital_c', 'St. Elara Community Hospital'),
  hospital('hospital_d', 'Harbourview Clinic'),
]

const untrainedModel = (modality, architecture) => ({
  modality,
  available: true,
  architecture,
  backend: 'pytorch',
  is_target_architecture: true,
  target_architecture: architecture,
  current_version: 0,
  training_status: 'NOT_TRAINED',
  primary_metric: 'f1',
  task_name: 'Task',
  metrics: null,
  evaluation_samples: null,
  last_updated: '2026-01-01T00:00:00+00:00',
  is_simulated: true,
})

/** The dashboard summary before any round has run. */
export const emptyOverview = {
  kpis: {
    participating_hospitals: 4,
    hospitals_online: 4,
    modalities: 3,
    fl_rounds_total: 0,
    fl_rounds_completed: 0,
    fl_rounds_failed: 0,
    models_trained: 0,
  },
  models: [untrainedModel('ehr', 'TabNet'), untrainedModel('ecg', 'CNN-BiLSTM'), untrainedModel('xray', 'EfficientNet-B3')],
  active_rounds: [],
  recent_rounds: [],
  hospitals: hospitals.map((h) => ({ ...h })),
  surveillance: { available: false, reason: 'No aggregated surveillance reports are configured.' },
  forecast: { available: false, reason: 'Surveillance data is not available.' },
  recent_activity: [],
  data_status: { simulated: true, label: 'SIMULATED / DEMONSTRATION DATA' },
}

export const trainedOverview = {
  ...emptyOverview,
  kpis: { ...emptyOverview.kpis, fl_rounds_total: 3, fl_rounds_completed: 2, fl_rounds_failed: 1, models_trained: 1 },
  models: [
    {
      ...untrainedModel('ehr', 'TabNet'),
      current_version: 2,
      training_status: 'TRAINED',
      metrics: { accuracy: 0.85, precision: 0.6, recall: 0.4, f1: 0.482, loss: 0.35 },
    },
    untrainedModel('ecg', 'CNN-BiLSTM'),
    untrainedModel('xray', 'EfficientNet-B3'),
  ],
}

const region = (id, name, status, count, score) => ({
  region_id: id,
  region_name: name,
  population: 200000,
  disease: 'dengue',
  time_period: '2026-W39',
  case_count: count,
  case_rate: count === null ? null : (count / 200000) * 100000,
  anomaly_score: score,
  hotspot_flag: status === 'CANDIDATE_HOTSPOT',
  status,
  status_label: { CANDIDATE_HOTSPOT: 'Potential hotspot', NORMAL: 'Normal', INSUFFICIENT_DATA: 'Insufficient data' }[status],
  reason:
    status === 'CANDIDATE_HOTSPOT'
      ? '4.2 standard deviations above the recent baseline of 40.0 cases/week.'
      : 'Within the range expected from recent weeks.',
  baseline_mean: status === 'INSUFFICIENT_DATA' ? null : 40,
  baseline_std: 5,
  baseline_points: 8,
  isolation_forest_score: null,
  cluster_id: null,
  adjacent_flagged_regions: [],
  reporting_hospitals: 2,
  suppressed_cells: status === 'INSUFFICIENT_DATA' ? 1 : 0,
  recent_weeks: ['2026-W38', '2026-W39'],
  recent_counts: [41, count],
})

const square = (x) => ({
  type: 'Polygon',
  coordinates: [
    [
      [x, 0],
      [x + 1, 0],
      [x + 1, 1],
      [x, 1],
      [x, 0],
    ],
  ],
})

const regions = [
  region('R01', 'Ashgrove', 'CANDIDATE_HOTSPOT', 120, 4.2),
  region('R02', 'Brackenfield', 'NORMAL', 38, -0.4),
  region('R03', 'Calderwick', 'INSUFFICIENT_DATA', null, null),
]

export const analyticsOptions = {
  diseases: [
    { id: 'dengue', label: 'Dengue' },
    { id: 'influenza_like_illness', label: 'Influenza-like illness' },
  ],
  regions: regions.map((r) => ({ region_id: r.region_id, name: r.region_name, population: r.population })),
  periods: [{ week_start: '2026-09-21', week_end: '2026-09-27', label: '2026-W39' }],
  latest_period: { week_start: '2026-09-21', week_end: '2026-09-27', label: '2026-W39' },
  data_status: { simulated: true, label: 'SIMULATED / DEMONSTRATION DATA', geometry_simulated: true, suppression_threshold: 5 },
}

export const hotspots = {
  disease: { id: 'dengue', label: 'Dengue' },
  time_period: { week_start: '2026-09-21', week_end: '2026-09-27', label: '2026-W39' },
  method: {
    method: 'Historical z-score (EARS C2 style, weekly)',
    baseline_weeks: 8,
    guard_weeks: 1,
    candidate_threshold_z: 3,
    elevated_threshold_z: 2,
  },
  regions,
  geojson: {
    type: 'FeatureCollection',
    features: regions.map((r, index) => ({
      type: 'Feature',
      geometry: square(index),
      properties: {
        region_id: r.region_id,
        region_name: r.region_name,
        status: r.status,
        status_label: r.status_label,
        case_count: r.case_count,
        case_rate: r.case_rate,
        anomaly_score: r.anomaly_score,
        hotspot_flag: r.hotspot_flag,
        cluster_id: null,
      },
    })),
  },
  summary: { CANDIDATE_HOTSPOT: 1, ELEVATED: 0, NORMAL: 1, INSUFFICIENT_DATA: 1 },
  disclaimer: 'A potential hotspot is a statistical signal. It is a candidate for further investigation, not a confirmed outbreak.',
  data_status: analyticsOptions.data_status,
}

export const startedRound = {
  id: 'ehr-r0001',
  round_number: 1,
  modality: 'ehr',
  status: 'WAITING_FOR_CLIENTS',
  config: {
    training: { local_epochs: 2, batch_size: 32, learning_rate: 0.003 },
    differential_privacy: { enabled: false, clip_norm: 1, noise_multiplier: 0 },
    min_participants: 2,
    auto_aggregate: true,
    model: { architecture: 'TabNet', backend: 'pytorch' },
  },
  base_model_version: 0,
  result_model_version: null,
  num_participants: 4,
  aggregation_status: 'PENDING',
  global_metrics: null,
  error: null,
  created_by: 'admin@fl-healthcare.demo',
  is_simulated: true,
  started_at: '2026-10-04T10:00:00+00:00',
  ended_at: null,
  participants: hospitals.map((h) => ({
    hospital_id: h.id,
    hospital_name: h.name,
    status: 'INVITED',
    num_samples: null,
    error: null,
    local_metrics: null,
  })),
  updates_received: 0,
  updates_expected: 4,
  evaluations_received: 0,
}
