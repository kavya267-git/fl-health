## Known issues

Recorded as they were noticed. Nothing listed here was rerun or changed after the fact; each item is left
for the project owner to decide.

1. **The laptop slept twice during the MIT-BIH runs** (around 17:50 and 18:12 on 1 Nov 2026). Running
   processes paused and resumed. This affects only wall-clock time, which is not reported from these runs
   (see *Run time*); rounds are computed identically before and after a pause.
2. **No +P (precision) for the Kaggle MIT-BIH and simulated runs.** Per-class precision was added to the
   harness for the patient-wise setting after those runs had started, so their Se / +P tables show a dash
   for +P. Their recall (= Se) is recorded. These runs did not save confusion matrices either, and +P cannot
   be reconstructed from what they did save: per-class recall and the held-out class counts give each
   class's true positives, but not its false positives (four unknowns for the four ECG classes, against two
   constraints from accuracy and macro-F1). Getting +P for these settings would need a rerun.
3. **The same setting gives slightly different FedAvg results in two experiments.** Kaggle MIT-BIH
   baselines (1d) and non-IID alpha = 1.0 (2b) use identical data, partitions and seeds: their local-only
   and centralised results are identical, but FedAvg gives macro-F1 0.842 ± 0.023 in 1d and
   0.829 ± 0.036 in 2b. Likewise FedAvg at alpha = 0.1 gives 0.430 ± 0.079 in 2b and 0.452 ± 0.106 as the
   mu = 0 row of 5b. Cause: `HospitalNode` derives each hospital's shuffling seed from the round id, and the
   harness puts the experiment's name in the round id, so the same seed trains with a different data order
   in each experiment. Nothing is wrong in either run; the gap shows how much FedAvg moves with training
   order alone, beyond the three seeds. Removing the name from the round id would make the two identical.
4. **On MIT-BIH, the small-noise DP points measure clipping, not noise.** With C = 1.0, every update was
   clipped (median norm before clipping about 11). At sigma = 0.001-0.03 every seed ends up predicting class V
   for every beat (V recall 1.000, macro-F1 0.05-0.09), and sigma = 0.1 (0.247) scores higher than sigma =
   0.001 (0.048). In the simulated setting, where updates are smaller (median norm about 3.5), the same
   small-noise levels still learn (macro-F1 0.975-0.986) but need 15 rounds instead of 5 to reach 0.9. A
   one-seed diagnostic (*Diagnostic for known issue 4*, after 3b) then tested whether the cause is that
   batch-norm running statistics are sent unclipped while the weights are clipped. It does not support that:
   with clipping at C = 1.0 and no noise, the model collapses whether the BN statistics are sent (a: final
   macro-F1 0.127, 80% of beats predicted V) or held at the global values (b: 0.032, every beat predicted V),
   while the same run without clipping learns (c: 0.815). Over the 20 rounds, both clip-only runs spend most
   rounds at macro-F1 0.236, which is the score of predicting N for every beat, never exceed 0.32 and then
   drop to predicting mostly or only V; (c) rises steadily. So clipping at C = 1.0 by itself reproduces the
   collapse, and the small-sigma DP rows are confounded by the clip norm, not by BN handling. One seed only;
   no DP row was rerun or changed. The reference (c) did not reproduce 3b's sigma = 0, seed 0 run exactly
   (0.815 against 0.832, with curves that differ from round 1) although the partition and training order were
   the same; the likely cause is that 3b ran with 5 PyTorch threads and the diagnostic with 8, which changes
   floating-point rounding (untested). All three diagnostic variants used 8 threads, so they are comparable
   with each other. A clip norm near the typical update norm would be the next thing to test; C = 1.0 was
   fixed by decision, so that is left for the project owner. Separately, BN statistics fall outside the
   privacy bound (stated in the accounting assumptions).
5. **In the patient-wise setting (1e) the centralised "upper bound" is not an upper bound.** At the final
   round, centralised scores macro-F1 0.372 ± 0.037 against FedAvg's 0.409 ± 0.007. For seeds 0 and 1 its
   curve peaks early (0.462 at round 3, 0.483 at round 4) and ends at 0.340 and 0.364; seed 2 has no early
   peak and ends at 0.413, while FedAvg and local only stay roughly flat at 0.28-0.45 from round 3 onwards;
   none of the curves is still rising at round 20. The protocol reports the final round and has no validation
   set for picking a round (choosing one by DS2 score would be tuning on test data), so the early peak is not
   used. Two consequences for the 1e tables: the "(upper bound)" label did not describe what happened, so 1e
   now labels the method "Centralised (pooled data)" (a label change only; no number changed), and "Rounds to
   95% of centralised macro-F1" (2.0 ± 1.0) compares against a low reference and should not be read as fast
   convergence. Likely explanation: pooled training on DS1 overfits to the 22 training patients, and
   inter-patient generalisation, not the training method, limits all three; untested. Nothing was rerun.
6. **The laptop slept during 1f.** Windows logged a sleep at 10:53 and a wake at 19:51 on 2 Nov 2026, during
   round 7 of the seed 1 pooled run, which took 32,354 s against roughly 40-100 s for its other rounds. As in
   item 1 this affects only wall-clock time, which is not reported from 1f; the rounds are computed
   identically before and after a pause.
7. **1f curves: pooled training peaks early again, and FedAvg moves from round to round.** As in 1e (item 5),
   the pooled model's best macro-F1 comes early (0.498 at round 1, 0.484 and 0.493 at round 3 for seeds 0, 1
   and 2) and it ends at 0.403, 0.409 and 0.429; the final round is reported, as fixed before the run. The
   FedAvg curves are not smooth near the end: at round 19 FedAvg scores 0.433, 0.435 and 0.397 against 0.485,
   0.483 and 0.462 at round 20, and its Se S over rounds 15-20 ranges from 0.10 to 0.21. As a check that
   round 20 does not decide the paired comparison, the same-seed, same-round 1f and 1e FedAvg values were
   compared at each of rounds 15-20: 1f is higher in both macro-F1 and Se S at all 18 seed-round pairs (1e's
   FedAvg Se S never exceeds 0.092 in those rounds). The direction of the paired differences therefore does
   not depend on the round chosen; their size does. This check uses DS2 scores only to describe the curves,
   not to choose what is reported.
