# HackerRank Orchestrate

Starter repository for the **HackerRank Orchestrate** 24-hour hackathon (September 2026).

## Buy or Wait?

Build an AI-powered financial agent that decides whether a user can safely afford a requested expense.

A user may ask: **"Can I afford this laptop?"**

Answering well takes more than the current balance. The agent must account for recurring expenses, pending payments, essential spending, confirmed income, available payment options, and relevant details buried in messages and images.

For every request, the agent decides whether the user should pay in full, pay partially, use installments, wait, or not proceed. The recommendation must be personalized: two users with the same balance can deserve different answers based on their commitments, priorities, payment preferences, and willingness to adjust flexible expenses.

A recommendation is safe only if the user can complete the full payment plan, cover essential expenses, and stay above their preferred minimum balance throughout the forecast period.

Read [`problem_statement.md`](./problem_statement.md) for the full task spec, input/output schema, allowed values, conflict-resolution rules, and submission format.

---

## Quick Start — Phases 0 and 1

Requires Python 3.10 or newer (verified with Python 3.10.12). This phase uses only
Python's standard library; no package installation or API configuration is needed.

From the repository root:

```bash
python3 -m src.main
python3 -m unittest discover -s tests -v
```

The CLI validates all nine input CSVs and writes
[`evaluation/phase1_data_audit.json`](evaluation/phase1_data_audit.json).
It does not calculate affordability or generate predictions. The starter command
`python3 code/main.py` runs the same audit and also works from another directory.

Override the input directory with `--dataset-root /path/to/dataset` or the
`DATASET_ROOT` environment variable (the explicit argument wins). Override the
artifact destination with `--audit-path /path/to/audit.json`; it must be outside
the input dataset. Defaults resolve relative to the source location, not the
working directory.

The final challenge solution, in a later phase, must generate root-level
`output.csv`. `dataset/output.csv` remains the read-only blank input template.

### Implemented ownership

| Responsibility | Owner |
|---|---|
| CLI and portable paths | `src/main.py`, `src/config.py` |
| Frozen domain records and original CSV cells | `src/models/` |
| Decimal, date, boolean, ID and pipe-list parsing | `src/data/parsers.py` |
| Column, row, uniqueness and template validation | `src/data/loader.py` |
| Join validation, lookup indexes and undirected adjacency | `src/data/indexes.py` |
| Exact dated FX lookup and conversion | `src/data/currency.py::CurrencyConverter` |
| Direction-only cash classification | `src/models/event.py::is_cash_event` |
| Linked-component traversal | `src/evidence/resolver.py::resolve_linked_component` |
| Protected-category and flexibility gates | `src/planning/spending_changes.py::can_stop`, `can_reduce` |
| Dataset measurements | `src/data/audit.py` |

Original CSV cells are retained in immutable `raw` mappings, including extra
columns. Money is parsed directly to `Decimal`; blank money stays `None`.
Profile fields use pipe-delimited parsing, immutable category/preference sets,
and ordered priority tuples. Priorities remain metadata only.

Indexes include both sample and evaluation requests so supplied offers and
evidence can join either set; the two request collections remain separate.
Missing references, duplicate IDs, cross-user links, malformed rows, and missing
required columns raise actionable errors. Missing image files are reported in the
audit; no image content is extracted. Linked components are iterative, unique,
and ordered lexicographically by event ID, without lifecycle interpretation.

`is_cash_event` is only the direction gate: a `True` result does not establish
spendable cash. Status/timing/lifecycle rules remain deferred. Spending helpers
only establish protection, user preference and event flexibility eligibility;
recurrence eligibility and optimization remain deferred.

FX requires the exact supplied date and direction. It does not invert pairs,
interpolate, or choose a nearby date. Same-currency conversion returns the original
Decimal; foreign conversion retains the exact product without currency rounding.
Future recurring-event FX date selection remains unresolved for Phases 2–3.

### Baseline and checks

The initial repository had empty `code/main.py` and `code/evaluation/main.py`,
no dependency manifest, no tests, and no established lint/type-check command.
The baseline unittest discovery ran 0 tests successfully. Existing dataset and
usage-report files are preserved. The standard-library unittest suite now covers
this phase; no random seed is needed because the foundation uses no randomness.

The audit defines overlap counts as the number of profiles with at least one
overlapping category, and linked-event count as rows with a nonblank link. It
reports evaluation requests separately from the combined sample/evaluation count.
The cadence test asserts the observed full-file counts and frequency set; these
are dataset regression checks, not hardcoded loading limits.

---

## Phase 2 — Recurrence calibration

Run the deterministic recurrence experiment:

```bash
python3 -m evaluation.calibrate_recurrence
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests evaluation code/main.py
git diff --check
```

`--dataset-root` and `DATASET_ROOT` work as in Phase 1. Use `--artifact-dir` to
write reports elsewhere. The experiment reads the 25 sample users' histories;
it does not run the 250-request challenge solution. The Phase 1 audit CLI is unchanged.

| Responsibility | Owner |
|---|---|
| Recurrence records, policy and confidence thresholds | `src/forecast/recurrence_models.py` |
| Eligibility, as-of lifecycle dedup, identity, cadence, amounts, confidence, source projection | `src/forecast/recurrence.py` |
| Prefix-only holdout and rolling backtests | `evaluation/recurrence_backtest.py` |
| Candidate policies, confounder manifest, sensitivity and artifact generation | `evaluation/calibrate_recurrence.py` |

The implemented default is category identity, calendar-aware cadence, and mean of
the last five amounts. This is moderately supported for historical amount point
prediction and strongly supported for dates in these visible histories. The
final financial policy remains weakly identified: no final label directly labels
a recurring occurrence. Mean estimation is not a conservative spending reserve.

Twelve one-factor policies are compared against the fixed category/calendar/median-last-3
experimental baseline. The generated report includes coverage, per-currency MAE,
relative errors, per-user stability, distinct-target outliers and rejected series.
Future projections preserve provenance and native currency. Salary predictions
are explicitly not confirmed income; message amendments and scheduled-event
reconciliation remain external. Future FX date selection remains unresolved.

Artifacts:

- `evaluation/recurrence_calibration.csv` — measured policy comparisons.
- `evaluation/recurrence_sensitivity.md` — changes across all 25 sample projections.
- `evaluation/phase2_calibration_manifest.json` — every sample's confounders and usage.
- `evaluation/phase2_recurrence_report.md` — methodology, selection, limitations and outliers.
- `evaluation/phase2_recurrence_details.json` — input hashes, diagnostics, grouping examples,
  native-currency metrics, paired-target comparisons and supporting measurements.

No balances, affordability scores, payment plans, message interpretation, image
extraction or model calls are computed in this phase.

---

## Important File Locations

```text
dataset/        Input data and the blank output template. Do not modify the input data.
code/           Your solution code.
output.csv      Final generated predictions in the repository root.
code.zip        ZIP file containing your complete solution for submission.
```

The blank template at `dataset/output.csv` is provided as a reference. Your final generated file must be the root-level `output.csv`.

---

## Repository Layout

```text
.
├── AGENTS.md                         # Rules for AI coding tools + transcript logging
├── problem_statement.md              # Full challenge statement
├── README.md                         # You are here
├── code/                             # Your solution code
├── output.csv                        # Final generated predictions
└── dataset/
    ├── requests.csv                  # 250 requests to evaluate — predict these
    ├── output.csv                    # Blank submission template
    ├── sample_requests.csv           # 25 solved examples
    ├── financial_profiles.csv        # Balances, minimum balance, priorities, preferences
    ├── financial_events.csv          # Historical, pending, and confirmed transactions
    ├── request_payment_options.csv   # Payment options available per request
    ├── exchange_rates.csv            # Fixed, dated conversion rates
    ├── messages.csv                  # Messages tied to users, requests, or events
    ├── images.csv                    # Payroll letters, statements, bills, receipts
    └── media/
        └── images/
```

Only `dataset/requests.csv` requires predictions. Everything else is context. Join user records with `user_id`, request records with `request_id`, supporting evidence with `related_event_id`, and exchange rates with the rate date and currency pair.

Amounts are in the user's `home_currency` — the dataset uses INR, ZAR, IDR, USD, and EUR, and every conversion rate you need is in `exchange_rates.csv`. All dates are `YYYY-MM-DD`. Live exchange rates, market data, and banking access are not required.

---

## What You Need to Build

For every row in `dataset/requests.csv`, produce one row in `output.csv` with:

| Column | Meaning |
|---|---|
| `request_id` | The request being answered |
| `amount_safe_to_pay` | Largest amount safe to pay on `request_date` before optional spending changes, after protecting essentials and the minimum balance |
| `affordability_status` | `affordable_now`, `affordable_with_plan`, `affordable_later`, or `not_affordable` |
| `recommended_payment_method` | `full_payment`, `partial_payment`, `installments`, `wait`, or `not_recommended` |
| `payment_plan` | Chronological `<YYYY-MM-DD>:<amount>` entries joined by `\|`, or `none` |
| `earliest_date_for_full_payment` | Earliest date the full amount is forecast safe as one payment; empty if never within the forecast |
| `spending_changes_needed` | Up to three `stop:<event_id>` / `reduce_to:<event_id>:<amount>` changes joined by `\|`, or `none` |
| `decision_explanation` | Short explanation and the financial facts behind it |

`0 <= amount_safe_to_pay <= requested_amount` must always hold. Installment plans must exactly match a supplied payment option, and only recurring expenses marked flexible may be changed.

`affordable_with_plan` means the full request is completed through a partial-payment schedule, installments, or permitted spending changes. Recommend `partial_payment` only when the request allows it, the user accepts it, `0 < amount_safe_to_pay < requested_amount`, and `earliest_date_for_full_payment` is on or before `desired_completion_date`. Use exactly two payments: pay `amount_safe_to_pay` on `request_date`, then pay the remaining amount on `earliest_date_for_full_payment`. The two payments must add up to `requested_amount`. Unlike installments, partial payment does not need to match a supplied payment option.

---

## Suggested Workflow

1. Inspect `dataset/sample_requests.csv` — 25 requests with completed output columns — to understand the expected format and decision style.
2. Reconstruct each user's financial state from `financial_profiles.csv` and `financial_events.csv`: separate recurring expenses from one-time events, reserve pending transactions, count confirmed salary only on its settlement date, and de-duplicate repeated representations of the same event.
3. When an event has a blank `amount`, find its `event_id` as `related_event_id` in `images.csv` and extract the amount from the linked image. Never treat a blank amount as zero. Pull in any other relevant messages, images, and payment options for the request.
4. Forecast forward and generate a plan that keeps the balance above the minimum at every step.
5. Verify deterministically — bounds, plan feasibility, schedule match, flexible-only spending changes — before writing `output.csv`.
6. Score yourself on the solved samples, then run the full dataset.

You may use any language or runtime. Python, JavaScript, and TypeScript are all reasonable choices.

---

## Requirements

Your solution must:

- be runnable from the terminal
- read the provided files from `dataset/`
- produce a valid `output.csv` with the exact required columns in the exact required order
- include one prediction for every `request_id` in `dataset/requests.csv`
- not use organizer-only files or hardcoded labels
- keep behavior deterministic where possible

If you use API keys or secrets, read them from environment variables. Never hardcode secrets in the repo.

---

## Evaluation

Your `output.csv` will be compared against hidden ground-truth values.

The scoring will consider:

- accuracy of `amount_safe_to_pay`
- correctness of `affordability_status`
- correctness of `recommended_payment_method` and `payment_plan`
- accuracy of `earliest_date_for_full_payment`
- validity of `spending_changes_needed`
- usefulness and consistency of `decision_explanation`

### Token Usage And Cost Analysis

Your `code.zip` must include one token-usage file:

```text
evaluation/usage_report.md
```

The report must cover model providers and names, model calls, input and output tokens, total and average tokens per request, estimated total and per-request cost. The reported values must correspond to the final full-dataset run that produced your `output.csv`.

---

## Chat Transcript Logging

This repo includes an [`AGENTS.md`](./AGENTS.md) file for AI coding tools. It asks compatible tools to append conversation summaries to a `log.txt` in the repository root — the same directory as `AGENTS.md`:

| Platform | Path |
|---|---|
| macOS / Linux | `<repo root>/log.txt` |
| Windows | `<repo root>\log.txt` |

The path resolves relative to `AGENTS.md`, so it stays correct across clones, renames, and checkouts. `log.txt` is gitignored — upload it as your chat transcript at submission time. Do not paste secrets into the chat.

In case, the harness you are using is not in the repo root, you can explicitly ask the agent to look for the AGENTS.md in this folder & then continue.

---

## Submission

Submit the following files as instructed by HackerRank:

| File | Description |
|---|---|
| `code.zip` | Full runnable solution, prompts/configuration, README, and the required `evaluation/` folder |
| `output.csv` | Predictions for every row in `dataset/requests.csv` |
| `chat_transcript` | The `log.txt` described above, showing how you developed or used the system |

Before submitting, confirm:

- `output.csv` has one row per row in `dataset/requests.csv` (250 rows plus the header).
- `output.csv` has the exact required columns in the exact required order.
- Every `amount_safe_to_pay` satisfies `0 <= amount_safe_to_pay <= requested_amount`.
- Every installment plan matches a supplied payment option, and every spending change targets a flexible recurring expense.
- Your runnable code, setup instructions, and `evaluation/` folder are included in `code.zip`.


## Phase 3 — Cash-flow simulation only

Run the timing experiments and generate all 25 sample baseline diagnostics:

```bash
python3 -m evaluation.run_timing_experiments
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests evaluation code/main.py
git diff --check
```

The evaluation command supports `--dataset-root PATH` and `--output-dir PATH`;
`DATASET_ROOT` also remains supported. It writes
`evaluation/phase3_timing_experiments.json`, `phase3_timing_report.md`, and
`phase3_simulation_diagnostics.json`. It reads supplied label payments as probes;
it does not generate recommendations or an output CSV.

Ownership:

- `src/forecast/simulation_models.py`: immutable cashflows, supplied candidate
  payments, spending effects, timing flags and ledger results.
- `src/forecast/timeline.py`: the inclusive D–D+90 horizon, source ordering and
  exact-date FX selection.
- `src/forecast/income.py` / `expenses.py`: credit/debit gates, final-payroll
  continuation guard, and validation/application of supplied spending changes.
- `src/forecast/preparation.py`: Phase 2 projections, explicit future records,
  narrow linked-lifecycle deduplication and explicit/projection reconciliation.
- `src/forecast/simulator.py`: balance application, safety and optional JSON trace.
- `evaluation/sample_timing_context.py`: reviewed sample-message confounders only;
  production modules do not import evaluation code.

Example (all values come from loaded data; no global simulator state):

```python
from src.data.loader import load_all_data
from src.data.indexes import build_indexes
from src.data.currency import CurrencyConverter
from src.forecast.preparation import prepare_forecast
from src.forecast.simulator import simulate, trace_json

data = load_all_data()
indexes = build_indexes(data)
request = data.sample_requests[0]
prepared = prepare_forecast(indexes, request.user_id, request.request_date)
result = simulate(
    indexes.profile_by_user_id[request.user_id], request.request_date,
    prepared.recurring_occurrences, prepared.explicit_occurrences,
    currency_converter=CurrencyConverter(data.exchange_rates),
    unresolved_sources=prepared.unresolved_sources,
    diagnostics=prepared.diagnostics,
)
# Optional debugging: print(trace_json(result))
```

Candidate payments are externally supplied `CandidatePayment(date, Decimal(...),
source)` values in the user's home currency. Spending changes are externally
supplied `SpendingChangeEffect(target_id, from_date, 'stop')` or `'reduce_to'` with
`new_amount` in the target's currency. They must target an allowed recurring debit;
protected categories, user preferences, source flexibility and reduction floors
are enforced. Unmatched/overlapping modifications and payments outside the horizon
raise errors rather than silently dropping parts of a proposal.

Safety includes opening and intermediate balances, not only daily closings.
`result.safe` concerns only the supplied flows and never decides request
affordability. Missing structured future amounts set `complete=False` and
`safe=False`; reported minima then cover known flows only. Semantic message/image
completeness remains unresolved. Exact missing FX raises an exception. The selected
recurrence and timing defaults are provisional; see the generated report for
conditional evidence and unresolved Phase 4+ questions.


## Phase 4 — Capacity only

Run the sample regression and the complete checks:

```bash
python3 -m evaluation.evaluate_capacity
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests evaluation code/main.py
git diff --check
```

The evaluator supports `--dataset-root PATH`, `DATASET_ROOT`, and `--output-dir
PATH` (outside the input dataset). It writes `evaluation/phase4_capacity_results.csv`,
`phase4_capacity_report.md`, and `phase4_capacity_details.json`. Results cover only
25 labeled samples. Financial artifacts are deterministic; measured runtime in the
report/details varies by run. No final output or unlabeled predictions are generated.

`src/planning/capacity.py` owns baseline reuse, analytical capacity, independent
verification and sequential date search. `capacity_models.py` owns context/results
and probe diagnostics. Continue the Phase 3 example with:

```python
from src.planning.capacity import prepare_capacity, evaluate_capacity

context = prepare_capacity(
    indexes.profile_by_user_id[request.user_id], request.request_date,
    prepared, CurrencyConverter(data.exchange_rates),
)
capacity = evaluate_capacity(context, request.requested_amount)
```

The result contains `amount_safe_to_pay`, `earliest_date_for_full_payment`, baseline
completeness/safety, analytical headroom, verification probes and diagnostics.
`calculate_safe_amount(context, amount)` and
`find_earliest_full_payment_date(context, amount)` are also available independently.
Preparation is reused; the capacity layer never reloads CSVs or reconstructs recurrence.

Capacity uses the actual payment-affected simulator checkpoints, with unchanged
prior checkpoints checked separately. This explicitly approved clarification is
recorded in architecture §25. Amounts round down to 0.01; positive capacity and
next-cent maximality are independently simulated. Unknown future amounts return
zero and no date. A baseline that already violates its floor cannot be repaired
by a payment; zero capacity then does not mean the baseline is safe.

The search checks D through D+90 on the original request-centered horizon and
ignores deadlines, payment preferences and optional spending changes. No Phase 5
recommendation, ranking or payment-plan generation is implemented. The measured
sample mismatches and recurrence-estimator comparisons are preserved without
request-specific production exceptions.
