# Phase 2 recurrence report

Data: 25 sample users, 2288 financial-event rows. Evaluation-request users were not used to select recurrence policy.
All sample-user histories are backtested, including users whose final labels are confounded. No final label is a direct recurrence target, so 0/25 are directly scored against final outputs; all 25 are included for historical testing and projection sensitivity. See the per-request manifest.

## Methods

Twelve one-factor policies compare exact/category/family identity, four cadence methods, six amount estimators, and one 28-day spend-rate alternative. Currency always partitions identity. Category identity includes event type; family identity pools only everyday groceries/dining/transport descriptions, preserving airfare and all other descriptions. No numbers are removed.
Calendar detection requires at least three consecutive months on one clamped day or month end. Otherwise it falls back to median inter-arrival. Recent median uses three intervals; mode ties use the smallest interval. Half-day interval medians round half up.
Amounts use Decimal precision 40, ROUND_HALF_UP to 0.01 per projected occurrence. Rolling spend uses the last 28 days ending at the last observation, divided by 28 and scaled to inferred cadence; only <=14-day groceries/dining/transport series with 28-day history qualify, otherwise the base estimator is retained with a diagnostic.
Confidence is mechanical, not probability: fewer than two observations is insufficient; fewer than three is low. High requires >=4 observations, maximum interval deviation/median <=0.10 and amount CV <=0.35. Medium allows deviation <=0.35. Staleness >2 median cycles, same-day observations, mixed categories or mixed salary descriptions make confidence low. Calendar-aligned series have zero calendar residual; raw interval MAD remains recorded. Low/insufficient series emit no occurrences.
Eligibility: settled cash activity strictly known before cutoff, known nonnegative amounts; debit expense/subscription/debt_payment types, or salary/payroll/wages without speculative/temporary/final/prorated markers. Other income is excluded, not relabeled salary. Exclusion reasons are saved. Historical income projections carry explicit non-confirmation provenance.
Linked graph dedup uses only visible nodes and edges at each cutoff. Components with multiple settled cash records are excluded as ambiguous, not financially resolved. Future lifecycle records cannot alter training.

## Backtest protocol and limitations

Hold out each sufficiently long group’s last observation; expanding rolling tests predict each observation after the first three. The cutoff is previous known observation + 1 day, never the target date. Grouping is stateless; all filtering, confidence, amounts and cadence use the training prefix only. Same-day target groups are excluded explicitly. Abstentions and short groups are counted; they are not zero errors.
Raw amount MAE is reported by currency, never averaged across currency units. Relative amount errors support cross-currency comparison; zero actual amounts are excluded from relative metrics and counted. Direction/category correctness is reported but largely guaranteed by structural grouping, not a semantic classifier score.
Event date is the provisional historical observation axis. Settlement must also precede the cutoff. This does not settle Phase 3 cash-flow timing. No current messages are interpreted and no future salary amendment is applied.

| Policy | Groups | Holdouts predicted/eligible | Date MAE days | Holdout mean relative amount error | Rolling mean relative error | HF rolling relative error |
|---|---:|---:|---:|---:|---:|---:|
| category_calendar_median3 | 247 | 243/243 | 0.0000 | 0.0736 | 0.1379 | 0.1753 |
| amount_latest | 247 | 243/243 | 0.0000 | 0.0778 | 0.1509 | 0.1933 |
| amount_mean_last_3 | 247 | 243/243 | 0.0000 | 0.0687 | 0.1283 | 0.1632 |
| amount_mean_last_5 | 247 | 243/243 | 0.0000 | 0.0623 | 0.1214 | 0.1540 |
| amount_median_last_5 | 247 | 243/243 | 0.0000 | 0.0679 | 0.1313 | 0.1668 |
| amount_max_last_3 | 247 | 243/243 | 0.0000 | 0.0837 | 0.1710 | 0.2178 |
| identity_exact | 676 | 198/289 | 4.2121 | 0.0490 | 0.0511 | 0.1834 |
| identity_family | 248 | 243/243 | 0.0000 | 0.0736 | 0.1379 | 0.1753 |
| cadence_median | 247 | 243/243 | 0.5062 | 0.0736 | 0.1379 | 0.1753 |
| cadence_recent_median | 247 | 243/243 | 0.5514 | 0.0736 | 0.1379 | 0.1753 |
| cadence_mode | 247 | 243/243 | 0.6543 | 0.0736 | 0.1379 | 0.1753 |
| spend_rolling28 | 247 | 243/243 | 0.0000 | 0.0687 | 0.1318 | 0.1671 |

Common predicted target IDs across all policies: 438. Paired summaries are in phase2_recurrence_details.json; conditional errors must be read alongside coverage.

## Selected default

Implemented default: category / calendar_aware / mean_last_5. Category identity and calendar-aware cadence are strongly supported for these visible histories: high coverage and zero next-date error; family ties category on sample projections, so the simpler category model is retained. Mean last five is moderately supported for point prediction: lower holdout and rolling relative error at identical coverage, including the high-frequency subset. It averages five observations with no learned weights or category exceptions. This does not establish a conservative essential-spending reserve. The full financial policy remains weakly identified by the 25 final labels, because none directly labels recurrence. Thresholds are provisional engineering safeguards, not statistically calibrated probabilities.

## Outliers

Five worst distinct-target date predictions (all policies):
- identity_exact event_2253 (transport): predicted 2023-10-22, actual 2024-01-25, error 95 days; training descriptions ('Local taxi',).
- identity_exact event_2160 (dining): predicted 2026-02-18, actual 2025-12-13, error 67 days; training descriptions ('Weekend food delivery',).
- identity_exact event_1524 (transport): predicted 2026-03-25, actual 2026-01-24, error 60 days; training descriptions ('Rail pass',).
- identity_exact event_1224 (groceries): predicted 2025-09-14, actual 2025-07-20, error 56 days; training descriptions ('Local market purchase',).
- identity_exact event_1428 (transport): predicted 2023-10-05, actual 2023-08-10, error 56 days; training descriptions ('Parking and tolls',).

Five worst distinct-target relative amount predictions (all policies; comparable across currencies):
- amount_latest event_643 (salary): predicted 1422.85, actual 782.57 EUR, absolute error 640.28, relative error 0.8182.
- amount_latest event_1140 (transport): predicted 58.44, actual 33.5 EUR, absolute error 24.94, relative error 0.7445.
- amount_max_last_3 event_2143 (dining): predicted 2239.04, actual 1291.44 INR, absolute error 947.60, relative error 0.7338.
- amount_max_last_3 event_342 (transport): predicted 1030376.90, actual 602450.01 IDR, absolute error 427926.89, relative error 0.7103.
- amount_max_last_3 event_315 (groceries): predicted 1831437.58, actual 1075064.04 IDR, absolute error 756373.54, relative error 0.7036.

Cause inspection: exact-description splitting turns a regular category stream into sparse merchant observations. Three coincidentally regular visits can earn medium confidence and then fail badly; the 95-day taxi miss is such a case. Amount outliers include abrupt salary changes unknowable from the prefix and variable spending extremes. No confidence label guarantees future continuation.

Irregular/rejected baseline series: 3. Full diagnostics, raw training event IDs, grouping examples and 37 category series completely missed by exact grouping are in phase2_recurrence_details.json.

## Remaining boundaries

Historical regularity does not establish future income confirmation. Final payroll markers, contract endings, salary/rent amendments and household income changes need external resolution. Low-confidence exclusion is not permission to ignore essential spending in a future safety model. Future FX selection, schedule reconciliation, event/settlement timing and same-day order remain Phase 3 questions. No simulator, capacity solver, payment logic, LLM, image extraction or output generation was built.

## Stability across users

- Mean-last-5 versus category_calendar_median3, holdout: lower mean relative error for 20 users, tied for 0, higher for 5.
- Mean-last-5 versus category_calendar_median3, rolling: lower mean relative error for 23 users, tied for 0, higher for 2.
- Mean-last-5 versus amount_latest, holdout: lower mean relative error for 20 users, tied for 0, higher for 5.
- Mean-last-5 versus amount_latest, rolling: lower mean relative error for 24 users, tied for 0, higher for 1.
- Mean-last-5 versus amount_median_last_5, holdout: lower mean relative error for 17 users, tied for 0, higher for 8.
- Mean-last-5 versus amount_median_last_5, rolling: lower mean relative error for 24 users, tied for 0, higher for 1.

Additional inspected irregular series (exact strategy, still recurring):
- user_01 transport local taxi: medium, interval deviation 0.0526; may represent coincidental merchant visits.
- user_01 groceries supermarket basket: medium, interval deviation 0.2000; may represent coincidental merchant visits.
- user_02 groceries local market purchase: medium, interval deviation 0.1429; may represent coincidental merchant visits.
- user_04 dining family dinner: medium, interval deviation 0.2000; may represent coincidental merchant visits.
- user_05 groceries fresh food shop: medium, interval deviation 0.2000; may represent coincidental merchant visits.

Representative category series missed by strict identity:
- request_01 dining: 8 exact-description groups versus one category series; descriptions: Bakery and snacks, Coffee shop, Family dinner, Lunch with colleagues, Neighbourhood restaurant, Quick-service meal, Takeaway order, Weekend food delivery.
- request_02 dining: 7 exact-description groups versus one category series; descriptions: Bakery and snacks, Coffee shop, Family dinner, Neighbourhood restaurant, Quick-service meal, Takeaway order, Weekend food delivery.
- request_02 transport: 6 exact-description groups versus one category series; descriptions: Commuter pass, Fuel refill, Metro and bus fares, Rail pass, Ride-hailing trip, Vehicle charging.
- request_03 dining: 5 exact-description groups versus one category series; descriptions: Bakery and snacks, Coffee shop, Lunch with colleagues, Quick-service meal, Takeaway order.
- request_03 groceries: 7 exact-description groups versus one category series; descriptions: Bulk pantry shop, Grocery delivery, Household groceries, Local market purchase, Neighbourhood grocer, Supermarket basket, Weekly produce market.

Five largest native-unit absolute amount errors (not a cross-currency ranking of financial impact):
- event_148 amount_max_last_3: 1022438.77 IDR; actual 1455258.76, predicted 2477697.53.
- event_353 amount_max_last_3: 842943.54 IDR; actual 1259307.64, predicted 2102251.18.
- event_352 amount_latest: 819964.58 IDR; actual 1282286.6, predicted 2102251.18.
- event_347 amount_latest: 788629.28 IDR; actual 2067659.14, predicted 1279029.86.
- event_315 amount_max_last_3: 756373.54 IDR; actual 1075064.04, predicted 1831437.58.
