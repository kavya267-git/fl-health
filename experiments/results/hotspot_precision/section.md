### Hotspot precision from recorded alert outcomes

An alert opens when a region becomes a potential hotspot; a health officer acknowledges it and records whether the rise was confirmed, not confirmed, or a reporting artefact. Precision = confirmed / all recorded outcomes; the second figure leaves reporting artefacts out (confirmed / (confirmed + not confirmed)). Only outcomes recorded by health officers count; outcomes an administrator recorded are listed separately below and left out of precision. Alerts without a recorded outcome are not counted.

| Alerts from | Alerts raised | Outcomes recorded | Confirmed | Not confirmed | Reporting artefact | Precision | Precision without artefacts |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Simulated data (DEMO OUTCOMES)** | 22 | 3 | 1 | 1 | 1 | 0.33 | 0.50 |
| Real data | 0 | 0 | 0 | 0 | 0 | - | - |

Outcomes recorded by administrators (not counted in precision): simulated data 0 (0 confirmed, 0 not confirmed, 0 reporting artefact); real data 0 (0 confirmed, 0 not confirmed, 0 reporting artefact).

**The simulated-data row uses demo outcomes.** They were entered through the alerts page, as a health officer, during a scripted demo walk-through of the alert workflow (demo database pinned to SIMULATION_END_WEEK=2026-11-02), not found by investigating anything, and the rises they refer to were injected by the simulator. The figures check that outcomes are recorded and counted correctly; they say nothing about how often the detector is right. Precision on real data needs real alerts with outcomes established by health officers.
