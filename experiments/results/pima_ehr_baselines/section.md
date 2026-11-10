### 1g. EHR baselines on real data: PIMA Indians Diabetes, four hospitals

Fixed before any run (10 November 2026); nothing below was changed after seeing a result. Real records: the PIMA Indians Diabetes Database (768 women of Pima heritage, 8 numeric features, diabetes within five years yes / no), split across the 4 hospitals with a Dirichlet label split (alpha = 1.0) drawn once with partition_seed. Each hospital holds out 25% of its records; held-out records are used only for the final scores, never for training, early stopping or choosing settings. Every setting is a default: the platform's TabNet and training settings for EHR (as in 1b), scikit-learn defaults for the forests and boosting. Zero values in glucose, blood pressure, skin fold, insulin and BMI are physiologically impossible and are treated as missing, as is usual for this dataset (the file itself codes them as 0); each hospital fills them by KNN imputation (k = 5) fitted on its own training split, and standardises with its own training-split mean and SD (nothing shared). The centralised model does the same on the union of the training splits. Scores are computed on the held-out records of all hospitals pooled (positive = diabetes); F1 and recall use the 0.5 threshold. 3 seeds (model initialisation, data order, forest / boosting random state); the partition is the same in every seed.

*Config:* `experiments/configs/pima_ehr_baselines.yaml`. *Run:* `python -m experiments.pima`. *Data:* PIMA Indians Diabetes Database, 768 records, 268 with diabetes (35%). Source: the National Institute of Diabetes and Digestive and Kidney Diseases (NIDDK), original owner of the data (donor V. Sigillito, Johns Hopkins University Applied Physics Laboratory), first described in Smith, J. W., Everhart, J. E., Dickson, W. C., Knowler, W. C. and Johannes, R. S. (1988), 'Using the ADAP learning algorithm to forecast the onset of diabetes mellitus', *Proceedings of the Annual Symposium on Computer Application in Medical Care*, pp. 261-265; obtained as OpenML dataset 37 (the UCI Machine Learning Repository file), downloaded from <https://openml.org/data/v1/download/37/diabetes.arff> and checked against MD5 `3cbaa3e54586aa88cf6aacb4033e4470`. Licence: listed by OpenML as "Public"; the file is not redistributed here (git-ignored, downloaded on first run). Zeros treated as missing: plasma glucose (2 h OGTT) 5, diastolic blood pressure 35, triceps skin fold 227, 2 h serum insulin 374, BMI 11; 376 records have at least one gap.

**Partition** (Dirichlet alpha = 1.0, partition seed 0, the same in every seed):

| Hospital | Training records | With diabetes | Held-out records | With diabetes |
| --- | --- | --- | --- | --- |
| hospital_a | 164 | 49% | 54 | 48% |
| hospital_b | 72 | 60% | 24 | 54% |
| hospital_c | 119 | 26% | 40 | 22% |
| hospital_d | 221 | 19% | 74 | 30% |

Scores below are on the 192 held-out records of all hospitals pooled (70 with diabetes), mean ± SD over 3 seeds. With so few held-out records, a difference of a few hundredths in ROC-AUC is within what a different split could change; the SD shows only seed-to-seed variation, not this sampling uncertainty.

| Model | Method | ROC-AUC | F1 | Recall (sensitivity) | Brier score (lower is better) |
| --- | --- | --- | --- | --- | --- |
| TabNet | Local only | 0.767 ± 0.016 | 0.587 ± 0.013 | 0.524 ± 0.008 | 0.204 ± 0.011 |
| TabNet | FedAvg | 0.754 ± 0.011 | 0.503 ± 0.016 | 0.414 ± 0.014 | 0.214 ± 0.007 |
| TabNet | Centralised | 0.804 ± 0.006 | 0.627 ± 0.023 | 0.610 ± 0.036 | 0.183 ± 0.008 |
| Logistic regression | Local only | 0.814 ± 0.001 | 0.635 ± 0.003 | 0.543 ± 0.000 | 0.167 ± 0.000 |
| Logistic regression | FedAvg | 0.778 ± 0.004 | 0.576 ± 0.002 | 0.486 ± 0.014 | 0.189 ± 0.001 |
| Logistic regression | Centralised | 0.808 ± 0.001 | 0.551 ± 0.010 | 0.452 ± 0.008 | 0.178 ± 0.000 |
| Random forest | Local only | 0.763 ± 0.003 | 0.589 ± 0.009 | 0.519 ± 0.016 | 0.186 ± 0.001 |
| Random forest | Centralised | 0.794 ± 0.003 | 0.589 ± 0.011 | 0.514 ± 0.000 | 0.178 ± 0.001 |
| Gradient boosting | Local only | 0.719 ± 0.001 | 0.571 ± 0.000 | 0.514 ± 0.000 | 0.228 ± 0.000 |
| Gradient boosting | Centralised | 0.796 ± 0.000 | 0.585 ± 0.000 | 0.514 ± 0.000 | 0.188 ± 0.000 |

Local only: each hospital's own model, scored on its own held-out records. FedAvg: the final global model (30 rounds), scored on every hospital's held-out records with that hospital's own preprocessing. Centralised: one model trained on the union of the training splits (preprocessing fitted on the union), the usual reference point, which the platform does not offer; it is not guaranteed to score highest. FedAvg is shown only for TabNet and logistic regression, whose parameters can be averaged. F1 and recall use the 0.5 threshold; the threshold was not tuned.

**Reading the results.**

- FedAvg scores below local-only training for both models that can be averaged (mean ROC-AUC: TabNet 0.754 vs 0.767; logistic regression 0.778 vs 0.814) and below centralised training on the pooled scores. On those scores the run shows no benefit from federation; the per-hospital scores added after the results (below) read differently.
- The hospitals' held-out diabetes shares range from 22% to 54%. Each local model learns its own hospital's base rate, and pooled ROC-AUC and Brier score reward that, which is one reason local-only training can match or beat centralised training here (logistic regression). Per-hospital scores were not part of the fixed protocol; they are below, as an analysis added after seeing the results.
- A possible reason for the FedAvg gap, not tested: each hospital standardises its features with its own training mean and SD (fixed in the protocol so that nothing is shared), so the averaged model sees differently scaled inputs at each hospital.
- These are results on one small public dataset split four ways; they show the pipeline on real records, not how the methods compare on real hospital EHR.

![Reliability plot](results/pima_ehr_baselines/reliability.png)

Calibration data per bin: `experiments/results/pima_ehr_baselines/reliability.csv`.

#### Analyses added after seeing the results

Not part of the protocol fixed before the run: requested in review on 10 November 2026, after the results above were seen. Same predictions, no model rerun. *Pooled*: ROC-AUC on all held-out records together (as in the table above). *Per hospital*: ROC-AUC on each hospital's own held-out records, averaged over the hospitals; it does not reward a model for learning each hospital's base rate. Both are means over the 3 seeds. 95% intervals: percentile bootstrap, 1,000 resamples (seed 0) of the held-out records, drawn within each hospital and shared by every model and method. The intervals cover only the sampling of these held-out records, not a different partition.

| Model | Method | ROC-AUC, pooled (95% CI) | ROC-AUC, per hospital, mean (95% CI) |
| --- | --- | --- | --- |
| TabNet | Local only | 0.767 (0.706-0.827) | 0.764 (0.701-0.825) |
| TabNet | FedAvg | 0.754 (0.693-0.811) | 0.801 (0.742-0.856) |
| TabNet | Centralised | 0.804 (0.746-0.858) | 0.822 (0.763-0.880) |
| Logistic regression | Local only | 0.814 (0.751-0.872) | 0.827 (0.766-0.886) |
| Logistic regression | FedAvg | 0.778 (0.718-0.842) | 0.825 (0.764-0.887) |
| Logistic regression | Centralised | 0.808 (0.748-0.869) | 0.821 (0.759-0.883) |
| Random forest | Local only | 0.763 (0.695-0.829) | 0.749 (0.675-0.819) |
| Random forest | Centralised | 0.794 (0.729-0.854) | 0.814 (0.753-0.875) |
| Gradient boosting | Local only | 0.719 (0.640-0.787) | 0.708 (0.618-0.786) |
| Gradient boosting | Centralised | 0.796 (0.734-0.857) | 0.819 (0.756-0.879) |

Per hospital, FedAvg compares differently with local-only training than on the pooled scores: TabNet 0.801 (FedAvg) vs 0.764 (local only), logistic regression 0.825 vs 0.827. So the pooled FedAvg gap comes at least partly from base rates: local models are rewarded on pooled scores for knowing their hospital's share of diabetes. Every interval in this table overlaps every other in the same column; with this few held-out records, no difference between methods here is clearly established.

Per-row values: `experiments/results/pima_ehr_baselines/added_analyses.csv`.
