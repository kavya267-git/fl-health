# Resource planning method

The resource planning page tells a hospital manager how many beds the coming weeks may need, for example
"Weeks 2–4: if the rest of the hospital stays as busy as today, with the expected dengue patients, you may need 36–43 of your 40 beds".

It is a **planning estimate**. It is built from a regional forecast, the hospital's recent share of cases and
assumed hospitalisation figures. It is not a prediction of who will be admitted. While the case counts are
simulated, the page says so and carries the "SIMULATED DATA – NOT REAL CASES" watermark.

## Inputs

| Input | Who sets it | Where it comes from |
| --- | --- | --- |
| Total beds, ICU beds, beds in use now (%) | The hospital's manager | Capacity form. Every entry is kept with a timestamp and audited (`HOSPITAL_CAPACITY_CHANGED`); the newest is used. |
| Share of cases admitted, share of admitted needing ICU, average length of stay | An administrator, per disease | Built-in defaults are labelled **"Assumed values, replace with local figures"** until an administrator changes them; changes are audited (`PLANNING_ASSUMPTIONS_CHANGED`). |
| Regional forecast for weeks 1–4, with its likely range for each region | Computed | The stored ensemble forecast (RESULTS.md Part C; docs/setup.md, "Ensemble forecasts"). |
| The hospital's weekly case reports | The hospital | The aggregated reports it sends for surveillance. |

Week 1 is the first week after the latest week of data.

## Steps

1. **Hospital share.** For each region the hospital reports cases for, the share is this hospital's reported
   cases divided by the region's reported cases over the **last 8 weeks**. Only weeks where both numbers are
   known are used: a suppressed hospital cell, or a regional total that is incomplete because of one, leaves
   that week out. A region with no usable week, or without a forecast, is listed as "not included". It is
   never guessed.
2. **Weekly admissions** = sum over those regions of (regional forecast × share) × share of cases admitted.
   The low and high values use the lower and upper ends of each region's likely range instead of its
   central value, summed over the regions. The result is **a range from the forecast's likely ranges**, not
   an 80% interval: adding the bounds of several regions (and of several diseases, for "all diseases
   together") assumes they are all low, or all high, at once, so the range is wider than an 80% interval for
   the hospital would be.
3. **Beds occupied.** Every patient admitted in a week is assumed to arrive at the start of that week and to
   stay the average length of stay. A week's beds are the patient-days falling in that week divided by 7, so
   a stay longer than a week carries over into the following weeks. ICU beds use the same rule for the ICU
   share of admissions.
4. **Total beds needed** = beds in use today (occupancy % × total beds) + the projected beds. The same
   occupancy % is applied to the ICU beds. **The rest of the hospital is assumed to stay as busy as today.**
   Today's occupancy already includes some patients with these diseases, and they are counted again among
   the projected patients, so the projection leans high.
5. **Highlighting.** A week is highlighted when the **high** total exceeds the hospital's beds; ICU is
   highlighted the same way against the ICU beds. Consecutive weeks with the same result are grouped into one
   sentence, giving the lowest low and highest high of the group.

The arithmetic is in `analytics/planning/projection.py`. Its inputs are gathered in
`backend/app/analytics/planning_service.py`.

## Worked example

The tests check these numbers (`analytics/tests/test_planning.py`, `backend/tests/test_planning.py`,
`frontend/src/test/planning.test.jsx`).

One region. The hospital's share is 0.25, 20% of cases are admitted, 10% of admitted patients need ICU, and
stays are 10 days. The hospital has 40 beds (4 ICU) at 75% occupancy, so 30 beds (3 ICU) are in use today.

| Week | Forecast low / central / high | Admissions (× 0.25 × 0.2) | Beds high: this week's admissions + last week's × 3/7 | Total high (+ 30) |
| --- | --- | --- | --- | --- |
| 1 | 80 / 100 / 130 | 4 / 5 / 6.5 | 6.5 | 36.5 |
| 2 | 90 / 120 / 160 | 4.5 / 6 / 8 | 8 + 6.5 × 3/7 = 10.79 | 40.79 |
| 3 | 100 / 140 / 190 | 5 / 7 / 9.5 | 9.5 + 8 × 3/7 = 12.93 | 42.93 |
| 4 | 70 / 100 / 140 | 3.5 / 5 / 7 | 7 + 9.5 × 3/7 = 11.07 | 41.07 |

A 10-day stay fills 7 days of the week of arrival and 3 days of the next, which gives the 3/7. Weeks 2–4 are
above 40 beds at the high end. The low totals of those weeks are 36.21, 36.93 and 35.64, so the page says:

> Weeks 2–4: if the rest of the hospital stays as busy as today, with the expected dengue patients, you may need 36–43 of your 40 beds. That
> could be more than you have.

> Week 1: if the rest of the hospital stays as busy as today, with the expected dengue patients, you may need 34–37 of your 40 beds.

At the high end, ICU needs 3 + 1.08 = 4.08 beds in week 2 against 4 ICU beds, so that week's ICU cell is
highlighted too.

## Limits

- **Assumptions matter most.** The defaults are placeholders, not clinical figures. Replace them with local
  numbers before relying on the page.
- **The hospital share assumes the future looks like the last 8 weeks.** A new ward, a referral change or a
  neighbouring hospital closing would break it.
- **Fixed stays.** Every patient stays exactly the average length of stay, and arrives at the start of the
  week. Real stays vary, so the numbers are averages, not peaks within a week.
- **The rest of the hospital is assumed to stay as busy as today.** Today's occupancy already includes some
  patients with these diseases, who are then counted again among the projected patients, so the projection
  leans high.
- **The low–high values are a range from the forecast's likely ranges**, summed over regions; they are not an
  80% interval for the hospital. Summing bounds makes the range wider than such an interval would be. On the
  other hand each region's likely range is often too narrow (RESULTS.md Part C: the ensemble's 80% range
  covered 74% of test forecasts), so the high value is still not a worst case.
