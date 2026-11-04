### Hotspot precision from recorded alert outcomes

An alert opens when a region becomes a potential hotspot; a health officer acknowledges it and records whether the rise was confirmed, not confirmed, or a reporting artefact. Precision = confirmed / all recorded outcomes; the second figure leaves reporting artefacts out (confirmed / (confirmed + not confirmed)). Alerts without a recorded outcome are not counted.

| Alerts from | Alerts raised | Outcomes recorded | Confirmed | Not confirmed | Reporting artefact | Precision | Precision without artefacts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Simulated data (DEMO OUTCOMES)** | 27 | 3 | 1 | 1 | 1 | 0.33 | 0.50 |
| Real data | 0 | 0 | 0 | 0 | 0 | - | - |

**The simulated-data row uses demo outcomes.** They were entered by hand during a demo walk-through of the alert workflow, not found by investigating anything, and the rises they refer to were injected by the simulator. The figures check that outcomes are recorded and counted correctly; they say nothing about how often the detector is right. Precision on real data needs real alerts with outcomes established by health officers.
