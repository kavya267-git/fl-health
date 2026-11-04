### Surveillance forecasting (simulated): weekly case counts per region and disease, 1-4 weeks ahead

Fixed before any run. Data: the SIMULATED weekly hospital reports the demo uses (12 simulated regions, 4 hospitals, 3 diseases, 104 weeks ending on the fixed week below, seed 2024, cells under 5 suppressed), aggregated to one series per region and disease (36 series). A regional week with a suppressed hospital cell has no total; such weeks are filled from earlier weeks only when they are inputs and are skipped when they are targets. As in the live forecast, a series is not forecast when more than 20% of its weeks are missing; the share is measured on weeks 1-64 only (the rule is fixed here, before any run). Week numbers count from 1 (the oldest week). Fitting window: weeks 1-64. Validation: forecasts whose target falls in weeks 65-84. Test: forecasts whose target falls in weeks 85-104. Every model is refitted at every forecast origin on all weeks up to and including that origin (rolling origin, expanding window), and forecasts 1-4 weeks ahead; only targets inside the window being scored count. Ensemble weights and the empirical intervals (LSTM, ensemble) use validation forecasts only and are frozen before the test window is scored. All forecasts and interval bounds are clipped at 0 (counts cannot be negative). Reported per model and horizon on the test window: MAE, RMSE, 80% interval coverage, and the MAE ratio against seasonal naive at the same horizon (below 1 = better than seasonal naive). The ensemble is not called better than its members unless the table shows it. One run; the LSTM uses a fixed seed.

*Config:* `experiments/configs/surveillance_forecasting.yaml`. Data: 26 SIMULATED series (10 excluded by the missing-weeks rule: acute_gastroenteritis:R02, acute_gastroenteritis:R03, acute_gastroenteritis:R07, acute_gastroenteritis:R08, acute_gastroenteritis:R09, acute_gastroenteritis:R10, acute_gastroenteritis:R12, dengue:R02, dengue:R08, influenza_like_illness:R02), weeks 2024-11-04 to 2026-10-26. Origins: weeks 61-103. One run (LSTM seed 0, 4 PyTorch threads).

**These results apply to the 26 series with enough reported weeks, not to all 36.** The 10 excluded series were mostly suppressed small counts: 20%-91% of their weeks 1-64 have no regional total because a hospital's count was below the suppression threshold, and their median weekly count is 22.5, against 0%-14% missing and a median of 56.5 for the series that were forecast. How the models would do on those sparse series was not measured.

Test window (targets in weeks 85-104), horizons 1-4 pooled, 2008 forecasts per model:

| Model | MAE | RMSE | 80% interval coverage | MAE ratio vs seasonal naive |
| --- | --- | --- | --- | --- |
| Naive (last value) | 17.07 | 26.29 | 0.870 | 0.931 |
| Seasonal naive (52 weeks) | 18.34 | 28.99 | 0.741 | 1.000 |
| ARIMA(p,d,0), least squares | 18.36 | 28.10 | 0.757 | 1.001 |
| Seasonal ARIMA(1,0,0)(0,1,0)[52], least squares | 17.85 | 27.76 | 0.743 | 0.973 |
| ARIMA(2,1,1), statsmodels | 16.41 | 26.19 | 0.754 | 0.895 |
| Prophet | 16.54 | 26.88 | 0.581 | 0.902 |
| LSTM (global) | 15.35 | 26.16 | 0.747 | 0.837 |
| Ensemble (ARIMA + Prophet + LSTM) | 14.52 | 24.85 | 0.736 | 0.792 |

By horizon (MAE / 80% coverage / MAE ratio vs seasonal naive):

| Model | 1 week ahead | 2 weeks ahead | 3 weeks ahead | 4 weeks ahead |
| --- | --- | --- | --- | --- |
| Naive (last value) | 14.98 / 0.771 / 0.817 | 16.31 / 0.869 / 0.890 | 17.75 / 0.912 / 0.968 | 19.24 / 0.928 / 1.049 |
| Seasonal naive (52 weeks) | 18.34 / 0.745 / 1.000 | 18.34 / 0.741 / 1.000 | 18.34 / 0.739 / 1.000 | 18.34 / 0.737 / 1.000 |
| ARIMA(p,d,0), least squares | 14.58 / 0.751 / 0.795 | 17.09 / 0.765 / 0.932 | 19.54 / 0.767 / 1.066 | 22.25 / 0.745 / 1.213 |
| Seasonal ARIMA(1,0,0)(0,1,0)[52], least squares | 17.18 / 0.737 / 0.937 | 17.77 / 0.749 / 0.969 | 18.15 / 0.745 / 0.990 | 18.30 / 0.739 / 0.998 |
| ARIMA(2,1,1), statsmodels | 13.95 / 0.757 / 0.761 | 15.56 / 0.749 / 0.848 | 17.19 / 0.761 / 0.938 | 18.94 / 0.751 / 1.033 |
| Prophet | 15.13 / 0.627 / 0.825 | 16.57 / 0.590 / 0.904 | 17.19 / 0.546 / 0.937 | 17.25 / 0.560 / 0.941 |
| LSTM (global) | 14.31 / 0.733 / 0.780 | 15.03 / 0.727 / 0.820 | 15.61 / 0.757 / 0.851 | 16.45 / 0.771 / 0.897 |
| Ensemble (ARIMA + Prophet + LSTM) | 13.30 / 0.723 / 0.725 | 14.40 / 0.743 / 0.785 | 14.92 / 0.737 / 0.814 | 15.46 / 0.739 / 0.843 |

Ensemble weights, fitted on the validation window only (each row sums to 1):

| Horizon | ARIMA(2,1,1), statsmodels | Prophet | LSTM (global) | Validation forecasts |
| --- | --- | --- | --- | --- |
| 1 | 0.343 | 0.350 | 0.308 | 482 |
| 2 | 0.235 | 0.356 | 0.409 | 482 |
| 3 | 0.255 | 0.439 | 0.306 | 482 |
| 4 | 0.184 | 0.491 | 0.325 | 482 |

Fits that failed (counted per series and origin; a failed fit has no forecast, and only forecasts that every model produced are scored): Seasonal ARIMA(1,0,0)(0,1,0)[52], least squares 78.

Coverage is the share of test targets inside the 80% interval (0.8 is the target). Intervals: the models' own for the statistical models and Prophet; for the LSTM and the ensemble, the 10th and 90th percentiles of their scaled validation errors. All values come from the run above; nothing was tuned on the test window. The series are simulated, so this checks the forecasting pipeline, not real-world accuracy.
