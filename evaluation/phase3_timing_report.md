# Phase 3 timing experiments

Reproduce: `python3 -m evaluation.run_timing_experiments`. All amounts remain Decimal; comparisons are within each home currency. No cross-currency ranking of raw amounts.

## Method

All 25 samples are included. Read supplied payment plans and supplied earliest full-payment dates as exogenous probes. No capacity or date search, recommendation, plan generation, spending search, message interpretation or image extraction is implemented. Baseline diagnostics contain no candidate payments. Labeled spending changes are disclosed but not applied to timing probes.

The same production simulator runs all variants. The horizon contains 91 dates (D through D+90). Opening balance and credit/debit/candidate block boundaries count for safety. Normal cashflows apply aggregate credits then debits, independent of CSV order. Missing future amounts produce incomplete known-flow diagnostics and never a safe result.

## Same-day ordering

Supplied-probe safety passes: cashflows first 18/36; candidate first 7/36. These are conditional safety observations, not final-label accuracy.

36 supplied probes; 13 requests have credits on probe dates. Numerically sensitive: 13 (request_02, request_03, request_04, request_06, request_08, request_11, request_13, request_17, request_18, request_19, request_21, request_22, request_23). Conditional horizon-safety flips: 7 (request_03, request_04, request_06, request_18, request_19, request_22, request_23).

| Request / probe | Minimum: cashflows first | Minimum: candidate first | Largest daily minimum difference | Safety flips |
|---|---:|---:|---:|---|
| request_02 / supplied_full_payment_date | 20962706.84 | 10558444.42 | 32046828.31 | False |
| request_03 / supplied_plan | 3611183.15 | 1516381.60 | 4365000.00 | True |
| request_03 / supplied_full_payment_date | 3611183.15 | 1516381.60 | 4365000.00 | True |
| request_04 / supplied_plan | 33819177.50 | 28591145.71 | 12693000.00 | True |
| request_04 / supplied_full_payment_date | 33819177.50 | 28591145.71 | 12693000.00 | True |
| request_06 / supplied_full_payment_date | 1069.25 | 704.15 | 620.40 | True |
| request_08 / supplied_plan | 227.41 | 39.18 | 996.60 | False |
| request_08 / supplied_full_payment_date | 227.41 | 39.18 | 996.60 | False |
| request_11 / supplied_full_payment_date | 46519205.15 | 34994577.35 | 13110000.00 | False |
| request_13 / supplied_plan | 1175.69 | 966.87 | 941.60 | False |
| request_13 / supplied_full_payment_date | 1175.69 | 966.87 | 941.60 | False |
| request_17 / supplied_full_payment_date | 162089.02 | 133639.81 | 206000.00 | False |
| request_18 / supplied_plan | 1947.76 | 1024.48 | 2310.00 | True |
| request_18 / supplied_full_payment_date | 1947.76 | 1024.48 | 2310.00 | True |
| request_19 / supplied_plan | 89459.31 | 78619.31 | 10840.00 | False |
| request_19 / supplied_full_payment_date | 103381.01 | 78619.31 | 39660.00 | True |
| request_21 / supplied_full_payment_date | 2625.85 | 1900.75 | 1574.40 | False |
| request_22 / supplied_full_payment_date | 556.51 | 412.70 | 573.17 | True |
| request_23 / supplied_plan | 30791.79 | 10134.79 | 38016.00 | True |
| request_23 / supplied_full_payment_date | 30791.79 | 10134.79 | 38016.00 | True |

Daily closing balance differences are exactly zero for ordering alternatives. These are conditional forecast differences, not end-to-end label scores. 4 requests (request_04, request_18, request_22, request_23) conditionally favor cashflows first after reviewing message facts and excluding unextracted amounts/unapplied spending changes. The other safety flips have explicit blockers listed below. Zero labels uniquely establish the policy independent of provisional recurrence. Default: cashflows before candidate. Evidence: **partially supported**, not uniquely disambiguated. It avoids declaring a within-day debit before a same-day credit when only dates are supplied; intraday bank ordering is still unknown.

## Event date versus settlement date

12 visible pending/scheduled rows have differing dates, including ignored or missing-amount rows. 9 baseline ledgers change: request_01, request_02, request_03, request_04, request_20, request_21, request_22, request_23, request_24. Conditional supplied-probe safety flips: 0 (none).

| Request | Relevant event IDs | Largest closing-balance difference | Horizon minimum difference |
|---|---|---:|---:|
| request_01 | event_102 | 567.6 | 0.00 |
| request_02 | event_185 | 1651100.0 | 0.00 |
| request_03 | event_254 | 95000 | 0.00 |
| request_04 | event_357 | 1704300 | 0.00 |
| request_16 | event_1442 | 0 | 0 |
| request_20 | event_1785, event_1786, event_1787 | 4470.00 | 0.00 |
| request_21 | event_1857 | 53.00 | 0.00 |
| request_22 | event_1961 | 43.00 | 0.00 |
| request_23 | event_2042 | 1553.20 | 0.00 |
| request_24 | event_2166 | 1830 | 0.00 |

Default: settlement date; absent settlement uses event date, overdue debit reserves on D. This follows cash settlement semantics, but visible labels do not resolve debit authorization reservation timing. FX continues to use explicit settlement date under either timing flag, isolating cash timing from rate valuation. Zero labels establish a timing winner.

## FX

| Pair | Rows | First date | Last date | Unique rates |
|---|---:|---|---|---|
| EUR → USD | 24 | 2024-04-15 | 2026-09-15 | 1.09 |
| EUR → ZAR | 22 | 2023-10-15 | 2026-01-15 | 20 |
| USD → EUR | 25 | 2023-10-15 | 2026-03-15 | 0.92 |
| USD → IDR | 30 | 2023-10-15 | 2026-06-15 | 15833.33 |
| USD → INR | 33 | 2024-01-15 | 2026-11-15 | 83.33 |

Future foreign-currency projections are needed for request_25; missing exact rates: 0. All pair rates are constant in the provided file, so these samples cannot distinguish future FX fallback strategies. No fallback is implemented.

## Baseline diagnostics

| Request | Currency | Starting balance | Floor | Recurring / explicit / pending | Minimum known-flow balance | Date | Complete structured inputs |
|---|---|---:|---:|---|---:|---|---|
| request_01 | ZAR | 58481.1 | 18000 | 49 / 2 / 1 | 26397.92 | 2024-06-01 | True |
| request_02 | IDR | 60383889.2 | 29158400 | 42 / 1 / 1 | 47227984.88 | 2025-08-13 | True |
| request_03 | IDR | 5810300 | 2668700 | 35 / 1 / 1 | 3611183.15 | 2019-09-14 | True |
| request_04 | IDR | 52206950 | 30686600 | 54 / 1 / 0 | 41284145.71 | 2024-06-13 | True |
| request_05 | ZAR | 46475.1 | 13100 | 41 / 0 / 0 | 7976.11 | 2026-02-04 | True |
| request_06 | EUR | 1942.4 | 800 | 66 / 0 / 0 | 1324.55 | 2026-01-13 | True |
| request_07 | INR | 218945.56 | 93000 | 29 / 0 / 0 | 188809.06 | 2024-09-13 | True |
| request_08 | EUR | 1536.57 | 800 | 55 / 0 / 0 | 1035.78 | 2025-04-12 | True |
| request_09 | EUR | 2231.1 | 600 | 32 / 0 / 0 | 622.26 | 2026-10-02 | True |
| request_10 | INR | 750155 | 225400 | 50 / 0 / 0 | 197797.36 | 2025-03-06 | True |
| request_11 | IDR | 63531795 | 34140600 | 43 / 0 / 0 | 46519205.15 | 2025-05-14 | True |
| request_12 | ZAR | 193089.89 | 43200 | 32 / 0 / 0 | 101447.70 | 2026-07-01 | True |
| request_13 | EUR | 2789.52 | 1300 | 51 / 1 / 0 | 1908.47 | 2024-05-14 | True |
| request_14 | EUR | 3931.74 | 2200 | 39 / 0 / 0 | -2005.23 | 2025-11-02 | True |
| request_15 | EUR | 1770.05 | 1200 | 51 / 0 / 0 | -2122.13 | 2026-04-04 | True |
| request_16 | INR | 362370 | 122400 | 52 / 0 / 0 | 362370 | 2023-08-12 | False |
| request_17 | INR | 550379.58 | 166100 | 52 / 1 / 0 | 408239.81 | 2026-03-14 | True |
| request_18 | EUR | 2486 | 1400 | 39 / 0 / 0 | 1947.76 | 2026-07-14 | True |
| request_19 | INR | 199545 | 92800 | 43 / 0 / 0 | 118279.31 | 2024-09-14 | True |
| request_20 | INR | 102609.05 | 64500 | 45 / 1 / 1 | 73793.25 | 2026-02-13 | False |
| request_21 | USD | 3911.35 | 1800 | 34 / 2 / 1 | 3475.15 | 2026-04-12 | True |
| request_22 | EUR | 1132.46 | 500 | 53 / 1 / 1 | 963.85 | 2024-12-14 | True |
| request_23 | ZAR | 51957.9 | 27000 | 43 / 1 / 1 | 35731.85 | 2025-05-14 | True |
| request_24 | INR | 85045 | 51000 | 64 / 1 / 0 | 64599.65 | 2026-01-13 | True |
| request_25 | IDR | 32063050 | 23379100 | 63 / 1 / 0 | 23668696.15 | 2024-03-14 | True |

Completeness covers supplied structured future amounts only, not semantic completeness of messages or images. request_16 (event_1442) and request_20 (event_1786) have unknown future debit amounts; their minima exclude those unknown values and are conditional, never certified safe. Source salary projections remain predictions, not confirmation. The later settled final-payroll marker event_390 suppresses older salary continuation for request_05, independently of the unchanged Phase 2 estimator. Contract termination, changed/delayed salaries, leave, rent changes and unspecified childcare require later evidence resolution.

## Confounders inspected

| Request | Messages | Images | Known confounders |
|---|---|---|---|
| request_01 | none | none | event_vs_settlement_timing, irregular_or_non_regular_income |
| request_02 | message_01 | none | event_vs_settlement_timing, explicit_message_facts_not_interpreted, messages_not_semantically_applied, payment_plan_mechanics |
| request_03 | message_02 | image_01 | event_vs_settlement_timing, explicit_message_facts_not_interpreted, image_or_missing_amount_resolution, irregular_or_non_regular_income, messages_not_semantically_applied |
| request_04 | message_03 | none | event_vs_settlement_timing, explicit_message_facts_not_interpreted, irregular_or_non_regular_income, messages_not_semantically_applied |
| request_05 | none | none | explicit_final_payroll_marker, irregular_or_non_regular_income |
| request_06 | message_04 | none | event_vs_settlement_timing, explicit_message_facts_not_interpreted, labeled_spending_changes_not_applied_to_baseline_probe, messages_not_semantically_applied, spending_optimization |
| request_07 | message_05 | none | event_vs_settlement_timing, explicit_message_facts_not_interpreted, messages_not_semantically_applied, payment_plan_mechanics |
| request_08 | message_06 | none | explicit_message_facts_not_interpreted, messages_not_semantically_applied |
| request_09 | none | none | irregular_or_non_regular_income |
| request_10 | message_07 | none | explicit_message_facts_not_interpreted, irregular_or_non_regular_income, messages_not_semantically_applied |
| request_11 | message_08 | none | explicit_message_facts_not_interpreted, irregular_or_non_regular_income, labeled_spending_changes_not_applied_to_baseline_probe, messages_not_semantically_applied, spending_optimization |
| request_12 | message_09 | none | explicit_message_facts_not_interpreted, irregular_or_non_regular_income, messages_not_semantically_applied, payment_plan_mechanics |
| request_13 | none | none | irregular_or_non_regular_income |
| request_14 | message_10 | none | explicit_message_facts_not_interpreted, irregular_or_non_regular_income, messages_not_semantically_applied |
| request_15 | message_11 | none | explicit_message_facts_not_interpreted, irregular_or_non_regular_income, messages_not_semantically_applied |
| request_16 | message_12 | image_02 | event_vs_settlement_timing, explicit_message_facts_not_interpreted, image_or_missing_amount_resolution, messages_not_semantically_applied, missing_or_ambiguous_future_cashflow |
| request_17 | none | image_03 | event_vs_settlement_timing, image_or_missing_amount_resolution, payment_plan_mechanics |
| request_18 | message_13 | none | explicit_message_facts_not_interpreted, messages_not_semantically_applied |
| request_19 | none | image_04 | image_or_missing_amount_resolution, payment_plan_mechanics |
| request_20 | message_14 | image_05 | event_vs_settlement_timing, explicit_message_facts_not_interpreted, image_or_missing_amount_resolution, messages_not_semantically_applied, missing_or_ambiguous_future_cashflow |
| request_21 | none | none | event_vs_settlement_timing, labeled_spending_changes_not_applied_to_baseline_probe, spending_optimization |
| request_22 | message_15 | none | event_vs_settlement_timing, explicit_message_facts_not_interpreted, messages_not_semantically_applied, payment_plan_mechanics |
| request_23 | message_16 | none | event_vs_settlement_timing, explicit_message_facts_not_interpreted, messages_not_semantically_applied |
| request_24 | message_17 | none | event_vs_settlement_timing, explicit_message_facts_not_interpreted, messages_not_semantically_applied |
| request_25 | none | none | future_fx_date_policy |

## Timing-context review

| Request | Conditional support eligible | Blockers | Reviewed message facts |
|---|---|---|---|
| request_01 | True | none | no messages |
| request_02 | False | unapplied_or_ambiguous_message_amendment | Salary increase effective 2025-08-15 is not applied. |
| request_03 | False | unapplied_or_ambiguous_message_amendment, unextracted_image_or_missing_historical_amount | Regular next payroll confirmed; historical blank payslip and one-off adjustment need separation. |
| request_04 | True | none | Unapproved quarterly bonus: excluded from recurring income; no future bonus added. |
| request_05 | True | none | no messages |
| request_06 | False | unapplied_or_ambiguous_message_amendment, labeled_spending_changes_unapplied | Temporary reduced pay continues for next cycle; mean history does not apply this amendment. |
| request_07 | False | unapplied_or_ambiguous_message_amendment | Confirmed salary delayed to 2024-09-23; scope beyond that cycle is unclear. Historical 15th projections are unamended. |
| request_08 | False | unapplied_or_ambiguous_message_amendment | Next salary changed for unpaid leave; no amendment applied. |
| request_09 | True | none | no messages |
| request_10 | True | none | Non-withdrawable pending gig payout is not recurring regular salary or confirmed credit. |
| request_11 | False | unapplied_or_ambiguous_message_amendment, labeled_spending_changes_unapplied | Changed confirmed base salary is not applied; speculative commissions are excluded. |
| request_12 | True | none | Seasonal contract ended; seasonal/temporary salary already excluded by history gate. |
| request_13 | True | none | no messages |
| request_14 | False | unapplied_or_ambiguous_message_amendment | Salary resumes and childcare begins; childcare amount unspecified, both amendments unapplied. |
| request_15 | False | unapplied_or_ambiguous_message_amendment | First confirmed salary amount/date absent from structured scheduled rows; amendment unapplied. |
| request_16 | False | unapplied_or_ambiguous_message_amendment, unextracted_image_or_missing_historical_amount, incomplete_structured_future_amounts | Next rent increases 12%; unresolved rent bill amount also requires evidence. |
| request_17 | False | unextracted_image_or_missing_historical_amount | no messages |
| request_18 | True | none | Internal historical transfer pair is not replayed or projected as recurring salary/expense. |
| request_19 | False | unextracted_image_or_missing_historical_amount | no messages |
| request_20 | False | unextracted_image_or_missing_historical_amount, incomplete_structured_future_amounts | Refund not credited: pending credit excluded. |
| request_21 | False | labeled_spending_changes_unapplied | no messages |
| request_22 | True | none | Unrealized portfolio valuation is non-cash and excluded. |
| request_23 | True | none | Uncredited prize claim: no speculative future prize cash added. |
| request_24 | True | none | Already-settled one-time prize is in opening balance; not replayed or projected. |
| request_25 | True | none | no messages |

## Limits and architecture boundary

Architecture §21 previously asked for safe-amount, earliest-date, status and plan match metrics. Those need Phase 4+ decisions. The Phase 3 clarification limits this experiment to supplied-flow traces and safety probes. No labels are hardcoded in production. Future evidence amendments can enter as explicit confirmed occurrences after reconciliation; no sample-specific override rules were needed to measure conditional sensitivity.

Low/insufficient recurrence stays omitted. The minimum is the earliest occurrence of the lowest opening/intermediate/closing balance. Equal-to-floor is safe only for complete inputs. Spending effects are supplied externally, must target recurring debits and respect protected/preference/flexibility/floor rules; they modify actual debits without creating savings credits.
