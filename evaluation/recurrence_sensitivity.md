# Recurrence projection sensitivity

Window: request_date through request_date + 90 days, inclusive; source occurrences only, no balance simulation.
Changed means different date/direction/category/currency aggregate occurrences; series IDs alone do not count.
Material means the maximum across tested policy pairs of the sum of absolute differences in total category/direction amounts exceeds 1% of requested_amount. Timing shifts alone need not be material.
Only exact supplied FX dates are used. With missing rates, the home-currency-only comparison is a lower bound; foreign materiality remains unresolved.

Requests changed: 25/25; material lower bound: 25; unresolved FX: 1.
Identity: 25; cadence: 25; amount: 25; rolling spend: 25; unaffected: 0.

| Request | Maximum difference (home currency) | Fraction of request | Policy pair | Material | FX unresolved |
|---|---:|---:|---|---|---|
| request_06 | 2907.6000 EUR | 4.6867 | amount_max_last_3 / identity_exact | True | False |
| request_09 | 747.5600 EUR | 4.4869 | amount_max_last_3 / identity_exact | True | False |
| request_04 | 48480106.7300 IDR | 3.8194 | amount_max_last_3 / identity_exact | True | False |
| request_08 | 3771.8200 EUR | 3.7847 | amount_latest / identity_exact | True | False |
| request_13 | 2126.3200 EUR | 2.2582 | amount_max_last_3 / identity_exact | True | False |
| request_11 | 26610657.4900 IDR | 2.0298 | amount_max_last_3 / identity_exact | True | False |
| request_19 | 79989.0500 INR | 2.0169 | amount_max_last_3 / identity_exact | True | False |
| request_16 | 226262.5500 INR | 1.8470 | amount_max_last_3 / identity_exact | True | False |
| request_10 | 265339.9300 INR | 0.9949 | amount_max_last_3 / identity_exact | True | False |
| request_22 | 710.3000 EUR | 0.9710 | identity_exact / cadence_mode | True | False |
| request_21 | 1430.4900 USD | 0.9086 | identity_exact / cadence_recent_median | True | False |
| request_01 | 22607.1800 ZAR | 0.8951 | amount_max_last_3 / identity_exact | True | False |
| request_17 | 224852.3900 INR | 0.8188 | amount_max_last_3 / identity_exact | True | False |
| request_03 | 4218822.4000 IDR | 0.7683 | identity_exact / cadence_mode | True | False |
| request_23 | 28444.4300 ZAR | 0.7482 | amount_max_last_3 / identity_exact | True | False |
| request_25 | 40289934.3900 IDR | 0.6660 | amount_max_last_3 / identity_exact | True | True |
| request_02 | 28487454.0300 IDR | 0.6191 | amount_max_last_3 / identity_exact | True | False |
| request_05 | 9252.5800 ZAR | 0.5974 | amount_mean_last_5 / identity_exact | True | False |
| request_18 | 1882.7000 EUR | 0.5800 | amount_max_last_3 / identity_exact | True | False |
| request_24 | 61601.1700 INR | 0.5621 | amount_max_last_3 / identity_exact | True | False |
| request_07 | 106369.9600 INR | 0.5389 | identity_exact / cadence_recent_median | True | False |
| request_12 | 33561.6300 ZAR | 0.5150 | amount_max_last_3 / identity_exact | True | False |
| request_15 | 1363.3700 EUR | 0.3700 | identity_exact / cadence_recent_median | True | False |
| request_14 | 1786.4100 EUR | 0.3299 | amount_max_last_3 / identity_exact | True | False |
| request_20 | 73224.7200 INR | 0.2411 | identity_exact / cadence_recent_median | True | False |

One-factor contrasts use category/calendar/median-last-3 as the fixed experimental baseline.
- identity: material in 25/25 requests; median largest one-factor difference/request = 0.6300.
- cadence: material in 11/25 requests; median largest one-factor difference/request = 0.0000.
- amount: material in 25/25 requests; median largest one-factor difference/request = 0.1213.
- spend: material in 24/25 requests; median largest one-factor difference/request = 0.0470.

Identity has the largest median amount effect, driven by exact-description fragmentation. Family and category produce identical sample projections. Cadence changes every schedule, but often preserves the total number/amount of occurrences.

These are recurrence projection differences, not changes to final labeled recommendations or affordability scores.
