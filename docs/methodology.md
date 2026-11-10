# Methodology

What each part of the system computes, and what it does not claim.

## Models and tasks

| Modality | Task | Model (PyTorch) | Input |
| --- | --- | --- | --- |
| EHR | Adverse in-hospital outcome, binary | TabNet: 3 attention steps, 16-d decision and attention embeddings, sparsemax masks, ghost batch norm, sparsity regulariser | 14 structured features, standardised with fixed clinical reference values |
| ECG | Beat class N / S / V / F, 4 classes | Three 1-D conv blocks (32, 64, 64) → BiLSTM (64 per direction) → mean pool → linear | 187-sample beat window (125 Hz) |
| X-ray | Finding present, binary | torchvision EfficientNet-B3 with a 2-way head; optional ImageNet initialisation (`XRAY_PRETRAINED=true`) | Greyscale image replicated to three channels |

EHR features are standardised with fixed reference means and spreads (`ml/ehr/features.py`) instead of
statistics computed from data, so every hospital preprocesses identically without anyone pooling
per-feature statistics.

Each task is separate. An F1 score for the ECG model and one for the EHR model measure different things and
are never placed on the same axis.

## Federated averaging

After local training, the coordinator computes

```
W_global = Σ_k (n_k / N) · W_k
```

where `W_k` are hospital k's weights, `n_k` its number of local training samples and `N = Σ n_k` over the
hospitals whose updates were accepted (`backend/app/federated/fedavg.py`). Floating-point tensors are
averaged in float64 and cast back; integer buffers (batch-norm step counters) are averaged and rounded.
Batch-norm running statistics are averaged like any other tensor.

The simulated hospitals are deliberately non-IID: different sizes, class balance, acuity, sensor noise and
scanner contrast. Plain FedAvg is known to converge more slowly under such heterogeneity; no correction
(FedProx, SCAFFOLD) is applied.

## Evaluation

The coordinator holds no evaluation data. After aggregation each participating hospital scores the new
global model on its **local held-out validation split** (25% of its data, fixed when the partition is
written) and returns a confusion matrix and the summed cross-entropy. The coordinator sums these, which
gives exactly the metrics a pooled evaluation would give:

- accuracy; loss (mean cross-entropy);
- precision, recall, F1: for the positive class in binary tasks, macro-averaged in the multi-class ECG task.

Limits: the validation split is also what you would tune against, so there is no untouched test set; the
splits are per-hospital random splits, not temporal; and metrics on simulated data say nothing about
clinical performance.

Each round also records, per hospital, the local training loss and the locally trained model's validation
metrics before averaging, so local and global models can be compared.

## Missing values (EHR)

Each hospital node fills gaps in its EHR features before training, with k-nearest-neighbour imputation
(k = 5, scikit-learn's `KNNImputer`): a missing value becomes the mean of that feature over the five most
similar training records that have it (`ml/ehr/imputation.py`).

- **Fitted on the hospital's own training split only.** Held-out records are filled from training
  neighbours; they never become neighbours, so held-out data cannot shape the training data or its own
  imputation. Tests check this directly (`ml/tests/test_imputation.py`, `ml/tests/test_hospital_node.py`).
- **Nothing leaves the hospital** except, when gaps were filled, counts: missing values per split and the
  number of training rows the imputer was fitted on.
- **Real gaps.** `prepare_real_data.py ehr --keep-missing` keeps rows with missing feature values for the node
  to impute (rows without a label are always dropped). Without the flag, such rows are dropped as before.
- **Simulated gaps.** The simulated hospitals have no gaps, so a round (or an experiment config) can blank a
  share of values completely at random (MCAR), for example 10%, to exercise the pipeline. The pattern is
  fixed per hospital and differs between hospitals. It is a test setting, not a property of the data.
- **Limits.** KNN imputation assumes values are missing at random given the other features; values that are
  missing *because* of the patient's state (a test not ordered for a well patient) are not modelled.
  Distances are measured on features scaled by the fixed clinical reference values in `ml/ehr/features.py`
  (the same ones the model uses), so a feature in large units does not dominate; nothing is fitted for the
  scaling.

## Simulated data

Used only in demo mode and labelled as simulated everywhere.

- **EHR** - vitals and labs drawn around a latent severity; the outcome follows a hand-written logistic
  model. Hospitals differ in age mix, acuity and measurement noise.
- **ECG** - beats built from Gaussian bumps for the P, Q, R, S and T waves, with class-specific changes
  (early beat with abnormal P for S; wide QRS, no P, inverted T for V; a blend for F), plus baseline wander
  and noise. They are cartoons of rhythms, not recordings.
- **X-ray** - 64×64 geometric phantoms; a "finding" is one or two soft bright blobs in a lung field. They
  are not radiographs.
- **Surveillance** - twelve fictional regions (a Voronoi tessellation), three diseases, 104 weeks of
  seasonal counts with autocorrelated local variation and over-dispersed noise. A few recent rises are
  injected so the hotspot layer has something to detect; they represent no real event.

## Hotspot candidates

Baseline method, chosen for transparency: a historical z-score in the style of CDC's EARS C2, adapted to
weekly data. For each region and week,

```
z = (count − mean(baseline)) / max(std(baseline), 1.0)
```

with the baseline being the 8 weeks that end 1 week before the tested week (the gap stops the start of a
rise from inflating its own baseline).

| Status | Rule |
| --- | --- |
| `CANDIDATE_HOTSPOT` ("Potential hotspot") | z ≥ 3 and at least 5 cases |
| `ELEVATED` | z ≥ 2 |
| `NORMAL` | otherwise |
| `INSUFFICIENT_DATA` | the week's count is missing or suppressed, or fewer than 6 usable baseline weeks |

Flagged regions that share a border are grouped so they can be reviewed together. An Isolation Forest
score (fitted on earlier weeks only) is reported as a second opinion and never changes the status.

What a flag means: the week is statistically unusual for that region. It is a candidate for further
investigation, **not a confirmed outbreak**. Known weaknesses: a short baseline reacts to the normal seasonal
upswing (on the simulated data roughly 4% of ordinary region-weeks reach the candidate threshold);
reporting delays, testing changes and holidays all produce the same signal; and there is no
multiple-comparison correction across regions. Rates use a population denominator only when one is supplied.

**Small-count suppression.** A hospital reports no count between 1 and 4. If any hospital's cell for a
region-week is suppressed, the regional total would only be a lower bound, so it is shown as not available
and the week is treated as missing.

**Clusters of potential hotspots (extra map layer).** The regions flagged as potential hotspots in the
week are grouped with K-Means (`analytics/hotspot/clusters.py`) on their location (centroid projected to
kilometres, equirectangular around the flagged regions' mean latitude) and their rates (case rate per
100,000 when populations are loaded, and the anomaly score), each standardised across the flagged regions.
k runs from 2 to min(5, n − 1) and the k with the highest silhouette is kept; the layer is shown only if
that silhouette is at least 0.25, the floor below which Kaufman & Rousseeuw (*Finding Groups in Data: An
Introduction to Cluster Analysis*, Wiley, 1990, ch. 2) find no substantial structure; and only
for groups of two or more regions. With fewer than three flagged regions there is nothing to cluster, and
the map says so. On the map, clustered regions get a purple halo labelled "cluster of potential hotspots",
which can be switched off. A cluster says that some flagged regions are close together and have similar
rates; it does not say they share a cause and is not a confirmed event. With only 12 simulated regions
and usually 0 to 4 flagged a week, the layer is often empty. A health officer sees a cluster only when at
least two of its regions are in their jurisdiction.

## Forecasting

Candidates (`analytics/forecasting/models.py`):

| Model | Idea |
| --- | --- |
| Naive | Next weeks equal the last observed week |
| Seasonal naive | Next weeks equal the same weeks one year earlier |
| ARIMA(p,d,0), least squares | Autoregression on the (optionally differenced) series; order chosen on an inner validation block of the training data |
| Seasonal ARIMA(1,0,0)(0,1,0)[52], least squares | Last year's value plus a decaying share of the current gap from last year |
| ARIMA(2,1,1), statsmodels | Added automatically if `statsmodels` is installed |

Validation is **rolling-origin**: for each of the last 12 weeks, every candidate is fitted on the weeks
before it only and forecasts up to the requested horizon. Errors are pooled into MAE and RMSE; the lowest
RMSE wins and is refitted on the full history to forecast. A prediction for week t never uses week t or any
later week - there is a test that tampers with later weeks and checks earlier predictions do not move.

Intervals are a normal approximation from each model's forecast standard error (80% and 95%), floored at
zero. They reflect the model's own error structure, not reporting error or structural change, so treat them
as optimistic. Series with more than 20% missing or suppressed weeks, or fewer than 30 points, are not
forecast; short gaps are linearly interpolated and counted.

Everything on the Forecasting page is labelled **Forecast / Prediction**. It is a projection, not confirmed
future cases.

## Explainability

Global and individual explanations are kept apart.

**EHR, individual (SHAP).** Shapley values by permutation sampling against a background sample
(`analytics/explainability/shapley.py`): each feature's value is the average change in the predicted
probability when that feature is switched from background values to the record's value, over random feature
orderings (each ordering also run in reverse). The values are additive: base value + contributions equals
the model's output, which is checked in tests against a closed form for linear models. This estimates the
same quantity as the `shap` package's Kernel and Permutation explainers; set
`EXPLAINER_BACKEND=shap-library` to use that package's KernelExplainer instead.

**EHR, global.** During evaluation each hospital computes mean |SHAP| per feature on up to 24 held-out
records and returns only those 14 averages (plus the direction of each feature's effect). The coordinator
weights them by records explained. No record leaves a hospital.

**ECG.** Occlusion sensitivity: a 12-sample window is replaced by a straight line between its edges and
the drop in the predicted class's log-odds is recorded for each position.

**X-ray.** Grad-CAM on the last convolutional block when the PyTorch EfficientNet-B3 is active; occlusion
sensitivity otherwise, labelled as such.

Individual explanations in the UI use a small set of **synthetic reference cases** held by the coordinator,
generated separately from every hospital partition and never used for training or evaluation. In a
deployment, explaining a real patient's prediction would happen inside the hospital.

Limits: SHAP explains the model, not the disease; correlated features share credit in ways that can
mislead; a heat map shows where the model is sensitive, not that it is correct. If no explanation can be
produced (untrained model, unsupported scope), the API says so with a reason instead of returning values.

## Privacy

**Architecture.** Raw data stays on hospital nodes; the list of what crosses the boundary is in
[architecture.md](architecture.md). This reduces the need to centralise patient data. It is not a privacy
guarantee: model updates can leak information about training data (membership inference, gradient
inversion).

**Differential privacy (prototype).** Chosen per round. At the hospital, before the update leaves:

1. the update Δ = W_local − W_global is scaled so that ‖Δ‖₂ ≤ `clip_norm`;
2. Gaussian noise N(0, (`noise_multiplier` · `clip_norm`)²) is added to every coordinate.

Accounting (`analytics/privacy/dp.py`), with its assumptions stated in the UI:

- the protected unit is one hospital's whole update in a round, not an individual patient;
- sensitivity = `clip_norm` (update present vs absent);
- each round is ρ-zCDP with ρ = 1 / (2 · noise_multiplier²); rounds add; ε = ρ + 2·√(ρ · ln(1/δ)), δ = 10⁻⁵;
- no subsampling amplification;
- batch-norm running statistics are sent unclipped and un-noised and fall outside the bound;
- with DP on (fixed or adaptive clip), the hospital does not report its update norm before clipping or
  whether it was clipped: neither is noised, so both would fall outside the bound. Without DP they are
  reported, for monitoring;
- a round run without DP has no bound, so a cumulative ε only holds if every round used DP.

**Adaptive clipping (option).** Instead of a fixed `clip_norm`, the clip norm can track a target quantile
γ of the hospitals' update norms (Andrew et al., "Differentially Private Learning with Adaptive Clipping",
NeurIPS 2021):

1. each hospital clips with the round's clip norm C and computes its bit b = 1 if ‖Δ‖₂ ≤ C, else 0;
2. it sends the centred bit (b − ½) plus Gaussian noise N(0, σ_b²); as with any DP round, it does not send its
   raw norm or whether it was clipped (here either would also reveal the bit);
3. its update is noised with z_Δ · C, where z_Δ = (z⁻² − (2σ_b)⁻²)^(−½) as in the paper, so that the update
   (sensitivity C) and the bit (sensitivity ½) together cost ρ = 1 / (2z²) per round: the same as a
   fixed-clip round with noise multiplier z, and the accounting above is unchanged;
4. after aggregation the coordinator computes b̄ = mean of the noised bits + ½ and sets the next round's
   clip norm to C · exp(−η (b̄ − γ)), η = 0.2 by default (the paper's geometric update). This uses noised
   bits only, so it is post-processing. The next adaptive round of the same model starts from that value.

σ_b is set from the share of each round's budget given to the bit (`quantile_budget_share`, default 0.1):
σ_b = z / (2√share), which keeps the split valid at every noise level. One difference from the paper: the
paper's server adds noise once to the sum of the bits and of the updates (central DP over many clients),
while here, as for the fixed clip, each hospital noises its own bit and update before they leave. With four
hospitals the bit average is therefore noisy, and the clip norm moves slowly: when every update is clipped
it grows on average by a factor exp(η γ) per round (about 1.105 for η = 0.2, γ = 0.5).

This is an unaudited prototype. With four hospitals, noise large enough to give a small ε destroys model
quality, and noise small enough to preserve quality gives an ε in the hundreds or thousands - the UI shows
whichever it is. It is not patient-level DP (that would need DP-SGD inside local training).

**Not implemented:** secure aggregation (the coordinator sees each hospital's update), encryption of
updates at rest, protection against a malicious coordinator or malicious hospitals (no robust
aggregation).

**Screening of incoming updates (advisory).** At aggregation, the coordinator describes each valid update by
two numbers: its size relative to the round's median update, and its cosine distance to the mean direction
of the *other* hospitals' updates (each scaled to unit length, so one very large update cannot drag the
reference towards itself). An Isolation Forest (scikit-learn, 200 trees, fixed seed) is fitted on those
numbers for the most recent 100 earlier updates of the same model plus the current round, and an update is
flagged as unusual when its anomaly score is above 0.6. Liu, Ting & Zhou ("Isolation Forest", ICDM 2008):
scores close to 1 indicate anomalies, while scores around 0.5 or below mean there is no distinct anomaly.
Nothing is scored
until 20 earlier updates exist (`backend/app/federated/screening.py`). A flag appears on the round page and
as `UPDATE_FLAGGED_UNUSUAL` in the audit log. **It never rejects an update**: the flagged update is averaged
like any other. Honest updates can be flagged too: hospitals with different patients move the model in
different directions, update directions drift as training converges, DP noise changes both numbers, and the
history is small. In the tests, an update reversed and scaled ×5 stands out clearly, while an honest
hospital can sit near the threshold. In a demo run of six honest EHR rounds (simulated hospitals, TabNet,
10 November 2026), the first round that was scored (round 6) flagged 2 of its 4 honest updates, with
scores of 0.51 and 0.50, just above the threshold then in use (scikit-learn's "auto" 0.5). **The threshold was
raised to 0.6 after observing these borderline flags on honest updates**, so it was chosen after seeing data,
not fixed in advance. The page still shows each update's raw score. Honest updates can still be flagged. It is a
prompt for a person to look, not a defence against poisoning (there is still no robust aggregation).

**Validation checks** (Settings page) inspect the running system: no patient-identifier-like columns in
the central schema; coordinator storage separate from hospital data and free of raw-data file types; every
accepted update passed structural validation; no stored count between 1 and 4; DP status; transport
encryption. They are evidence about this deployment, not a proof of privacy or a compliance assessment.

## Audit trail

Every significant event appends an entry containing the previous entry's hash and its own SHA-256 over
(timestamp, actor, action, hospital, round, model version, status, details, previous hash). Verification
recomputes the chain and reports the first entry that was altered, removed or reordered.

This makes tampering detectable. It does not make the database immutable: someone who can rewrite every row
can rebuild a consistent chain. Stronger guarantees would need the latest hash to be anchored somewhere the
database owner cannot change.
