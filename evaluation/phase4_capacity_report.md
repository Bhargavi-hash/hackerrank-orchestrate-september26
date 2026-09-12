# Phase 4 capacity regression

Reproduce: `python3 -m evaluation.evaluate_capacity`. Only the 25 supplied sample rows are evaluated; no predictions for the 250 unlabeled requests or final output CSV are generated.

## Algorithm and scope

Prepare recurrence and explicit occurrences once per request/policy; build one unchanged baseline. Calculate the minimum headroom over the simulator checkpoints affected by a request-date payment. Earlier checkpoints must separately be safe. Clamp to [0, requested amount], round down to 0.01 (same convention for every supplied currency), and independently resimulate the amount and the next cent when within the requested cap. Missing future debit uncertainty yields zero and no provable full-payment date. A zero result on an already-unsafe baseline is a terminal capacity bound, not a claim that the baseline is safe.

Search every calendar date sequentially from D through D+90 inclusive, preserving the original request-centered 91-date forecast. No rolling extension, deadline restriction, payment preference filter, spending changes, recommendation or plan ranking. The full-payment probe uses the exact requested amount. Phase 3 timing and Phase 2 recurrence defaults are unchanged.

## Architecture clarification

The literal all-checkpoint formula conflicted with maximality under cashflows-first timing: opening 100, today credit 100, floor 20 gives all-checkpoint headroom 80, but payment 180 is safe. The user explicitly selected payment-affected checkpoints for the actual maximum. The implementation reads the simulator candidate-payment checkpoint marker rather than redefining order. The saved counterexample independently verifies 180 safe and 180.01 unsafe.

The official “next 90 days” wording and architecture §§22/24 anchor the forecast at the request. No text requires extending it 90 days beyond a later payment. Within that fixed horizon, delaying a payment leaves earlier balances higher and later balances equal. Therefore safe(d) implies safe(d+1) for these exogenous flows—even with recurring obligations. No genuine non-monotonic counterexample exists under current semantics; tests verify this and the implementation still scans dates sequentially.

## Safe-amount metrics

Exact matches: **0/25**.

| Currency | Rows | MAE | Median absolute error | Maximum absolute error |
|---|---:|---:|---:|---:|
| EUR | 8 | 153.14 | 84.405 | 597.74 |
| IDR | 5 | 874623.648 | 840445.68 | 2195745.71 |
| INR | 7 | 22066.944286 | 5400 | 122500 |
| USD | 1 | 31.05 | 31.05 | 31.05 |
| ZAR | 4 | 6232.8825 | 3826.65 | 16858.08 |

Median relative error (absolute error / labeled nonzero safe amount): 0.171452; mean: 0.402179; denominator: 25 rows. Mean error normalized by requested amount: 0.147577. Raw errors in different currencies are never averaged together.

## Earliest-date metrics

Exact matches: **14/25**, including 7 both-blank matches. Paired present dates: 12.

Within 1 / 3 / 7 days among paired present dates: **7 / 7 / 7**. Missing/present mismatches: **6**. Median / maximum absolute paired date error: **0 / 61 days**.

## Every sample result

| Request | Currency | Predicted safe | Labeled safe | Predicted full date | Labeled full date | Complete baseline | Likely causes |
|---|---|---:|---:|---|---|---|---|
| request_01 | ZAR | 8397.92 | 25256 | — | 2024-03-03 | True | recurrence_amount, recurrence_identity |
| request_02 | IDR | 18069584.88 | 17229139.2 | 2025-10-15 | 2025-09-15 | True | missing_message_amendment, recurrence_amount |
| request_03 | IDR | 942483.15 | 873000 | 2019-11-15 | 2019-11-15 | True | missing_image_amount, missing_message_amendment, recurrence_amount |
| request_04 | IDR | 10597545.71 | 8401800 | 2024-06-15 | 2024-06-15 | True | recurrence_amount |
| request_05 | ZAR | 0.00 | 737 | — | — | True | recurrence_identity |
| request_06 | EUR | 524.55 | 603.3 | 2026-01-15 | 2026-01-15 | True | missing_message_amendment, recurrence_amount |
| request_07 | INR | 95809.06 | 87170.56 | 2024-10-15 | 2024-10-23 | True | missing_message_amendment, recurrence_amount |
| request_08 | EUR | 235.78 | 284.57 | — | 2025-04-15 | True | missing_message_amendment, recurrence_amount |
| request_09 | EUR | 22.26 | 166.61 | — | 2026-07-04 | True | recurrence_amount, recurrence_identity |
| request_10 | INR | 0.00 | 12700 | — | — | True | recurrence_amount, recurrence_identity |
| request_11 | IDR | 12378605.15 | 12510645 | 2025-05-15 | 2025-07-15 | True | missing_message_amendment, recurrence_amount |
| request_12 | ZAR | 58247.70 | 65164 | — | 2026-04-05 | True | recurrence_amount, recurrence_identity |
| request_13 | EUR | 608.47 | 433.4 | — | 2024-05-15 | True | recurrence_amount |
| request_14 | EUR | 0.00 | 597.74 | — | — | True | missing_message_amendment, recurrence_identity |
| request_15 | EUR | 0.00 | 83.05 | — | — | True | missing_message_amendment, recurrence_identity |
| request_16 | INR | 0.00 | 122500 | — | 2023-08-12 | False | missing_image_amount, missing_message_amendment |
| request_17 | INR | 242139.81 | 243849.58 | 2026-04-15 | 2026-03-15 | True | missing_image_amount, recurrence_amount |
| request_18 | EUR | 547.76 | 462 | 2026-09-15 | 2026-09-15 | True | recurrence_amount |
| request_19 | INR | 25479.31 | 28820 | 2024-09-15 | 2024-09-15 | True | missing_image_amount, recurrence_amount |
| request_20 | INR | 0.00 | 5400 | — | — | False | missing_image_amount |
| request_21 | USD | 1574.40 | 1543.35 | 2026-04-03 | 2026-04-15 | True | unknown |
| request_22 | EUR | 463.85 | 475.46 | 2025-01-15 | 2025-01-15 | True | recurrence_amount |
| request_23 | ZAR | 8731.85 | 9152 | 2025-07-15 | 2025-07-15 | True | recurrence_amount |
| request_24 | INR | 13599.65 | 13420 | — | — | True | recurrence_amount |
| request_25 | IDR | 289596.15 | 1425000 | — | — | True | recurrence_amount |

## Mismatch analysis

The approved checkpoint clarification changes headroom for 0 of these 25 samples. It therefore does not explain the zero exact safe-amount matches. Independently replaying labeled safe amounts succeeds on only 8/25 current forecasts; the remaining rows fail or are incomplete. This directly demonstrates upstream forecast disagreement, rather than a capacity formula fitted to labels. Source rows at each limiting checkpoint and every date-search probe are saved in the details artifact.

Causes are hypotheses grounded in visible source rows and measured estimator sensitivity, not confirmed semantic resolutions. Counts are nonexclusive: missing_image_amount=5, missing_message_amendment=9, recurrence_amount=19, recurrence_identity=7, unknown=1.

- **request_01**: Capacity changes under median_last_3, latest; sensitivity is not proof of the correct estimator. No recurring income survives history/continuation gates. Review source eligibility; do not admit speculative income to fit labels. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_02**: message_01: Salary increase effective 2025-08-15 is not applied. Capacity changes under median_last_3, latest; sensitivity is not proof of the correct estimator. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_03**: Unextracted image-linked amounts: image_01/event_253. message_02: Regular next payroll confirmed; historical blank payslip and one-off adjustment need separation. Capacity changes under median_last_3, latest; sensitivity is not proof of the correct estimator. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_04**: Capacity changes under median_last_3, latest; sensitivity is not proof of the correct estimator. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_05**: No recurring income survives history/continuation gates. Review source eligibility; do not admit speculative income to fit labels. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_06**: message_04: Temporary reduced pay continues for next cycle; mean history does not apply this amendment. Capacity changes under median_last_3, latest; sensitivity is not proof of the correct estimator. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_07**: message_05: Confirmed salary delayed to 2024-09-23; scope beyond that cycle is unclear. Historical 15th projections are unamended. Capacity changes under median_last_3, latest; sensitivity is not proof of the correct estimator. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_08**: message_06: Next salary changed for unpaid leave; no amendment applied. Capacity changes under median_last_3, latest; sensitivity is not proof of the correct estimator. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_09**: Capacity changes under median_last_3, latest; sensitivity is not proof of the correct estimator. No recurring income survives history/continuation gates. Review source eligibility; do not admit speculative income to fit labels. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_10**: Capacity changes under median_last_3; sensitivity is not proof of the correct estimator. No recurring income survives history/continuation gates. Review source eligibility; do not admit speculative income to fit labels. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_11**: message_08: Changed confirmed base salary is not applied; speculative commissions are excluded. Capacity changes under median_last_3, latest; sensitivity is not proof of the correct estimator. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_12**: Capacity changes under median_last_3, latest; sensitivity is not proof of the correct estimator. No recurring income survives history/continuation gates. Review source eligibility; do not admit speculative income to fit labels. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_13**: Capacity changes under median_last_3, latest; sensitivity is not proof of the correct estimator. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_14**: message_10: Salary resumes and childcare begins; childcare amount unspecified, both amendments unapplied. No recurring income survives history/continuation gates. Review source eligibility; do not admit speculative income to fit labels. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_15**: message_11: First confirmed salary amount/date absent from structured scheduled rows; amendment unapplied. No recurring income survives history/continuation gates. Review source eligibility; do not admit speculative income to fit labels. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_16**: Unextracted image-linked amounts: image_02/event_1442. message_12: Next rent increases 12%; unresolved rent bill amount also requires evidence. Incomplete future forecast uses terminal zero capacity and blank date. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_17**: Unextracted image-linked amounts: image_03/event_1545. Capacity changes under median_last_3, latest; sensitivity is not proof of the correct estimator. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_18**: Capacity changes under median_last_3, latest; sensitivity is not proof of the correct estimator. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_19**: Unextracted image-linked amounts: image_04/event_1700. Capacity changes under median_last_3, latest; sensitivity is not proof of the correct estimator. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_20**: Unextracted image-linked amounts: image_05/event_1786. Incomplete future forecast uses terminal zero capacity and blank date. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_21**: No isolated upstream cause established by the tested alternatives. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_22**: Capacity changes under median_last_3, latest; sensitivity is not proof of the correct estimator. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_23**: Capacity changes under median_last_3, latest; sensitivity is not proof of the correct estimator. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_24**: Capacity changes under median_last_3, latest; sensitivity is not proof of the correct estimator. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.
- **request_25**: Capacity changes under median_last_3, latest; sensitivity is not proof of the correct estimator. Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.

Largest mismatches by request-normalized error (not mixed-currency native units):

- request_16: error 122500.00 INR; 1 of requested amount.
- request_09: error 144.35 EUR; 0.866395 of requested amount.
- request_01: error 16858.08 ZAR; 0.667488 of requested amount.
- request_13: error 175.07 EUR; 0.185928 of requested amount.
- request_04: error 2195745.71 IDR; 0.172989 of requested amount.

## Recurrence downstream comparison

All 25 requests are rerun with only the recurrence amount estimator changed. This includes every amount-sensitive mismatch and avoids cherry-picking improvements. Message/image inputs and timing remain unchanged.

| Estimator | Safe exact | Mean error / requested | Date exact | Presence mismatches |
|---|---:|---:|---:|---:|
| mean_last_5 | 0 | 0.147577 | 14 | 6 |
| median_last_3 | 0 | 0.154015 | 15 | 6 |
| latest | 0 | 0.165685 | 15 | 6 |

| Alternative vs mean-5 | Safe improve / worsen / tie | Date improve / worsen / tie | Both no worse, one better | Both no better, one worse | Tradeoffs |
|---|---|---|---:|---:|---:|
| median_last_3 | 11 / 8 / 6 | 1 / 0 / 24 | 11 | 8 | 0 |
| latest | 5 / 13 / 7 | 1 / 0 / 24 | 5 | 12 | 1 |

Mean-last-5 remains defensible as the provisional default: it has the lowest mean request-normalized safe-amount error of these three estimators. Median-last-3 improves more individual safe amounts but worsens others, and both alternatives gain only one exact date. Neither alternative dominates across the two fields and all rows. Zero exact safe amounts under all three policies indicates that changing just this estimator does not reproduce benchmark capacity semantics. Historical point-prediction support is separate from capacity calibration; unresolved evidence remains a confounder. No request-specific estimator switch is made. Detailed per-request alternatives and improvement/worsening IDs are saved in phase4_capacity_details.json.

## Performance

Measured with perf_counter_ns; times include forecast preparation and capacity simulations, exclude shared CSV loading/index construction and artifact writing. Timing measurements vary by run; financial results do not.

| Estimator | Preparation seconds | Capacity seconds | Total, 25 requests | Average/request | Linear estimate, 250 (not measured) |
|---|---:|---:|---:|---:|---:|
| mean_last_5 | 0.094349 | 1.295371 | 1.38972 | 0.055589 | 13.897201 |
| median_last_3 | 0.091342 | 1.234556 | 1.325897 | 0.053036 | 13.258974 |
| latest | 0.091337 | 1.201879 | 1.293216 | 0.051729 | 12.932158 |

## Remaining boundaries

Capacity mismatches cannot be fixed by Phase 5 payment selection, deadline eligibility or preference handling: those are intentionally independent. Upstream recurrence/confirmation questions need later calibration/evidence resolution, and image-backed amounts need the later extraction phase. Unknown future amounts for requests 16 and 20 deliberately remain terminal. Missing historical amounts can also affect recurrence even when baseline_complete is true. Salary/rent amendments and unspecified childcare remain unapplied. No model calls or inferred amounts are introduced.

The Phase 3 explicit-event, pending-debit and exact-FX rules remain unchanged. This run does not isolate every possible identity, cadence or timing error; residual mismatch causes are hypotheses, not proof that the capacity arithmetic is wrong. Partial-payment composability remains documented in architecture, but no partial plan is constructed here.
