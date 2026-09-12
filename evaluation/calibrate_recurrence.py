"""Phase 2 only: holdouts, rolling backtests, and source-projection sensitivity."""
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from datetime import date, timedelta
from decimal import Decimal, localcontext
from itertools import combinations
from pathlib import Path

from src.config import REPO_ROOT
from src.data.currency import CurrencyConverter, MissingExchangeRateError
from src.data.indexes import build_indexes
from src.data.loader import Dataset, load_all_data
from src.forecast.recurrence import (ARITHMETIC, HIGH_FREQUENCY_CATEGORIES,
    decimal_median, infer_recurring_series, normalize_description, project_recurring_series,
    recurrence_exclusion_reason)
from src.forecast.recurrence_models import DEFAULT_POLICY, RecurrencePolicy
from .recurrence_backtest import backtest_history, summarize_folds


BASELINE = RecurrencePolicy(policy_id='category_calendar_median3', amount_method='median_last_3')


def candidate_policies() -> tuple[RecurrencePolicy, ...]:
    """12 one-factor contrasts, not a Cartesian parameter search."""
    policies = [BASELINE]
    for amount in ['latest', 'mean_last_3', 'mean_last_5', 'median_last_5', 'max_last_3']:
        policies.append(replace(BASELINE, policy_id=f'amount_{amount}', amount_method=amount))
    for identity in ['exact', 'family']:
        policies.append(replace(BASELINE, policy_id=f'identity_{identity}', identity_method=identity))
    for cadence in ['median', 'recent_median', 'mode']:
        policies.append(replace(BASELINE, policy_id=f'cadence_{cadence}', cadence_method=cadence))
    policies.append(replace(BASELINE, policy_id='spend_rolling28', spend_rate_method='rolling_28'))
    return tuple(policies)


def json_default(value: object) -> object:
    if isinstance(value, (Decimal, date)):
        return str(value)
    raise TypeError(f'cannot serialize {type(value)}')


def json_text(value: object) -> str:
    return json.dumps(value, default=json_default, indent=2, sort_keys=True) + '\n'


def flow_signature(occurrences: tuple) -> dict[tuple, Decimal]:
    totals = defaultdict(Decimal)
    for o in occurrences:
        totals[(o.date, o.direction, o.category, o.currency)] += o.amount
    return dict(totals)


def category_totals(occurrences: tuple, home_currency: str, converter: CurrencyConverter) -> tuple[dict, list]:
    totals = defaultdict(Decimal)
    missing = []
    for o in occurrences:
        try:
            amount = converter.convert_amount(o.amount, o.currency, home_currency, o.date)
            totals[(o.direction, o.category)] += amount
        except MissingExchangeRateError:
            missing.append((str(o.date), o.currency, home_currency))
    return dict(totals), sorted(set(missing))


def compare_projections(left: tuple, right: tuple, home: str, converter: CurrencyConverter) -> dict:
    """No balances. L1 category/direction totals avoid credit/debit cancellation.

    If any foreign rate is missing, compare only home-currency occurrences on BOTH
    sides: that is a lower bound, never an invented FX rate or zero foreign flow.
    """
    a, missing_a = category_totals(left, home, converter)
    b, missing_b = category_totals(right, home, converter)
    missing = sorted(set(missing_a + missing_b))
    if missing:
        a, _ = category_totals(tuple(o for o in left if o.currency == home), home, converter)
        b, _ = category_totals(tuple(o for o in right if o.currency == home), home, converter)
    with localcontext(ARITHMETIC):
        difference = sum((abs(a.get(k, Decimal(0))-b.get(k, Decimal(0))) for k in a.keys() | b.keys()), Decimal(0))
    return {'changed': flow_signature(left) != flow_signature(right),
            'total_difference_home_currency': difference, 'missing_fx': missing}


def sample_sensitivity(data: Dataset, indexes, policies: tuple[RecurrencePolicy, ...]) -> tuple[list, dict]:
    converter = CurrencyConverter(data.exchange_rates)
    rows = []
    projections_by_request = {}
    for request in data.sample_requests:
        results, projections = {}, {}
        for policy in policies:
            result = infer_recurring_series(indexes.events_by_user_id[request.user_id], request.request_date, policy)
            results[policy.policy_id] = result
            projections[policy.policy_id] = tuple(o for series in result.series
                for o in project_recurring_series(series, request.request_date, request.request_date + timedelta(days=90)))
        projections_by_request[request.request_id] = results
        base = projections[BASELINE.policy_id]
        base_signature = flow_signature(base)
        changed_buckets = set()
        for projected in projections.values():
            signature = flow_signature(projected)
            changed_buckets.update(key[1:] for key in base_signature.keys() | signature.keys()
                                   if base_signature.get(key, Decimal(0)) != signature.get(key, Decimal(0)))
        comparisons = {}
        for policy in policies[1:]:
            comparison = compare_projections(base, projections[policy.policy_id],
                indexes.profile_by_user_id[request.user_id].home_currency, converter)
            comparison['material'] = comparison['total_difference_home_currency'] > request.requested_amount * Decimal('0.01')
            comparison['materiality_unresolved'] = bool(comparison['missing_fx']) and not comparison['material']
            comparisons[policy.policy_id] = comparison
        # Report maximum across ALL policy pairs, with one-factor counts separately.
        pairs = []
        for left, right in combinations(policies, 2):
            comparison = compare_projections(projections[left.policy_id], projections[right.policy_id],
                indexes.profile_by_user_id[request.user_id].home_currency, converter)
            pairs.append((comparison['total_difference_home_currency'], left.policy_id, right.policy_id, comparison))
        largest = max(pairs, key=lambda v: (v[0], v[1], v[2]))
        rows.append({
            'request_id': request.request_id, 'home_currency': indexes.profile_by_user_id[request.user_id].home_currency,
            'requested_amount': request.requested_amount, 'comparisons_to_baseline': comparisons,
            'any_changed': any(c['changed'] for c in comparisons.values()),
            'identity_changed': any(comparisons[f'identity_{x}']['changed'] for x in ['exact', 'family']),
            'cadence_changed': any(comparisons[f'cadence_{x}']['changed'] for x in ['median', 'recent_median', 'mode']),
            'amount_changed': any(c['changed'] for key, c in comparisons.items() if key.startswith('amount_')),
            'spend_rate_changed': comparisons['spend_rolling28']['changed'],
            'maximum_pair_difference': largest[0], 'maximum_pair': list(largest[1:3]),
            'maximum_pair_relative_difference': largest[0] / request.requested_amount,
            'material': largest[0] > request.requested_amount * Decimal('0.01'),
            'has_unresolved_fx': any(c['missing_fx'] for _, _, _, c in pairs),
            'sensitive_series': sorted({s.series_id for p in policies for s in results[p.policy_id].series
                if (s.direction, s.category, s.currency) in changed_buckets}),
        })
    return rows, projections_by_request


def calibration_manifest(data: Dataset, indexes, sensitivity: list) -> list:
    rows = []
    for request, measured in zip(data.sample_requests, sensitivity):
        events = indexes.events_by_user_id[request.user_id]
        messages = [m for m in indexes.messages_by_user_id.get(request.user_id, ())
                    if m.sent_at.date() <= request.request_date and m.request_id in (None, request.request_id)]
        confounders = []
        if request.spending_changes_needed != 'none':
            confounders.append('spending_optimization')
        if request.recommended_payment_method in {'installments', 'partial_payment'}:
            confounders.append('payment_plan_mechanics')
        if any(e.amount is None for e in events):
            confounders.append('image_or_missing_amount_resolution')
        if messages:
            confounders.append('explicit_message_facts_not_interpreted')
        if any(e.event_date != e.settlement_date for e in events if e.direction != 'non_cash'):
            confounders.append('event_vs_settlement_timing')
        if any(e.direction == 'credit' and 'final' in normalize_description(e.description) for e in events):
            confounders.append('explicit_final_payroll_marker')
        if any(recurrence_exclusion_reason(e, request.request_date) in {'unconfirmed_income_family', 'non_regular_salary'}
               for e in events if e.direction == 'credit'):
            confounders.append('irregular_or_non_regular_income')
        if measured['has_unresolved_fx']:
            confounders.append('future_fx_date_policy')
        rows.append({
            'request_id': request.request_id,
            'included_for_recurrence_calibration': False,
            'reason': 'Final affordability labels contain no next-occurrence target; direct scoring requires later phases.',
            'historical_holdout_included': True,
            'projection_sensitivity_included': True,
            'candidate_for_later_label_validation': not confounders,
            'sensitive_series': measured['sensitive_series'],
            'known_confounders': confounders,
            'message_ids_requiring_resolution': [m.message_id for m in messages],
            'interpretation': 'No message amendments applied. Historical backtests remain valid before these current messages.',
        })
    return rows


def run_calibration(data: Dataset) -> dict:
    indexes = build_indexes(data)
    policies = candidate_policies()
    all_folds, counts_by_policy, final_results = {}, {}, {}
    snapshot_caches = {r.user_id: {} for r in data.sample_requests}
    for policy in policies:
        folds, counts, results = [], Counter(), []
        for request in data.sample_requests:
            events = indexes.events_by_user_id[request.user_id]
            user_folds, user_counts = backtest_history(events, request.request_date, policy,
                prepared_snapshots=snapshot_caches[request.user_id])
            folds.extend(user_folds)
            counts.update(user_counts)
            results.extend(infer_recurring_series(events, request.request_date, policy).series)
        all_folds[policy.policy_id] = tuple(folds)
        counts_by_policy[policy.policy_id] = dict(counts)
        final_results[policy.policy_id] = results
    sensitivity, results_by_request = sample_sensitivity(data, indexes, policies)
    summaries = []
    for policy in policies:
        folds = all_folds[policy.policy_id]
        holdout = summarize_folds(f for f in folds if f.is_holdout)
        rolling = summarize_folds(folds)
        high_frequency = summarize_folds(f for f in folds if f.category in HIGH_FREQUENCY_CATEGORIES)
        summaries.append({
            **asdict(policy), **counts_by_policy[policy.policy_id],
            'holdout': holdout, 'rolling': rolling, 'high_frequency_rolling': high_frequency,
            'high_frequency_series_count': sum(s.category in HIGH_FREQUENCY_CATEGORIES and s.is_recurring for s in final_results[policy.policy_id]),
            'monthly_series_count': sum(s.is_recurring and s.cadence.model == 'calendar_month' for s in final_results[policy.policy_id]),
            'sample_requests_sensitive': sum(row['comparisons_to_baseline'].get(policy.policy_id, {}).get('changed', False) for row in sensitivity),
        })
    # Same target IDs for fair date/amount comparisons where identities differ.
    predicted_sets = [{f.target_event_id for f in folds if f.predicted_date is not None} for folds in all_folds.values()]
    common = set.intersection(*predicted_sets)
    paired = {key: summarize_folds(f for f in folds if f.target_event_id in common)
              for key, folds in all_folds.items()}
    predicted_folds = [f for folds in all_folds.values() for f in folds if f.predicted_date is not None]
    def worst_distinct(key):
        seen, selected = set(), []
        for f in sorted(predicted_folds, key=lambda f: (-key(f), f.policy_id, f.target_event_id)):
            if f.target_event_id not in seen:
                selected.append(asdict(f))
                seen.add(f.target_event_id)
            if len(selected) == 5:
                break
        return selected
    date_outliers = worst_distinct(lambda f: f.date_error)
    amount_outliers = worst_distinct(lambda f: f.relative_error or Decimal(0))
    raw_amount_outliers = worst_distinct(lambda f: f.amount_error)
    per_user_amount_comparison = []
    for request in data.sample_requests:
        user_metrics = {}
        for key in [BASELINE.policy_id, 'amount_mean_last_5', 'amount_latest', 'amount_median_last_5']:
            user_folds = [f for f in all_folds[key] if f.user_id == request.user_id]
            user_metrics[key] = {'holdout': summarize_folds(f for f in user_folds if f.is_holdout),
                                 'rolling': summarize_folds(user_folds)}
        per_user_amount_comparison.append({'request_id': request.request_id, 'policies': user_metrics})
    irregular_recurring = [asdict(s) for s in final_results['identity_exact'] if s.is_recurring
                          and s.diagnostics.maximum_interval_deviation > 0][:10]
    baseline_series = final_results[BASELINE.policy_id]
    irregular = [asdict(s) for s in baseline_series if not s.is_recurring or
                 (s.diagnostics.maximum_interval_deviation and s.diagnostics.maximum_interval_deviation > 0)]
    grouping_examples, missed = [], []
    for request_id, results in results_by_request.items():
        base = results[BASELINE.policy_id]
        exact = results['identity_exact']
        for s in base.series:
            matching = [e for e in exact.series if set(e.event_ids) & set(s.event_ids)]
            if len(matching) > 1:
                example = {'request_id': request_id, 'category': s.category,
                    'category_series_id': s.series_id, 'category_confidence': s.confidence.value,
                    'descriptions': sorted({indexes.events_by_event_id[e].description for e in s.event_ids}),
                    'exact_groups': [{'series_id': e.series_id, 'events': len(e.event_ids),
                                      'confidence': e.confidence.value,
                                      'description': indexes.events_by_event_id[e.event_ids[0]].description} for e in matching],
                    'family_groups': [{'series_id': f.series_id, 'events': len(f.event_ids), 'confidence': f.confidence.value}
                        for f in results['identity_family'].series if set(f.event_ids) & set(s.event_ids)]}
                grouping_examples.append(example)
                if s.is_recurring and not any(e.is_recurring for e in matching):
                    missed.append(example)
    history_counts = Counter()
    for request in data.sample_requests:
        result = infer_recurring_series(indexes.events_by_user_id[request.user_id], request.request_date)
        history_counts.update(d.reason for d in result.history_diagnostics)
    return {'policies': summaries, 'paired_common_target_count': len(common), 'paired_results': paired,
            'sensitivity': sensitivity, 'manifest': calibration_manifest(data, indexes, sensitivity),
            'date_outliers': date_outliers, 'amount_outliers': amount_outliers,
            'raw_amount_outliers': raw_amount_outliers, 'per_user_amount_comparison': per_user_amount_comparison,
            'irregular_recurring_examples': irregular_recurring,
            'irregular_or_rejected_series': irregular, 'grouping_examples': grouping_examples,
            'missed_by_exact_grouping': missed, 'history_exclusion_counts': dict(sorted(history_counts.items())),
            'sample_user_count': len(data.sample_requests),
            'source_event_count': sum(len(indexes.events_by_user_id[r.user_id]) for r in data.sample_requests),
            'default_policy': asdict(DEFAULT_POLICY),
            'folds': all_folds,
            'series_diagnostics': {key: [asdict(s) for s in final_results[key]]
                                   for key in [BASELINE.policy_id, 'identity_exact', 'identity_family']}}


def fmt(value: object) -> str:
    return str(value.quantize(Decimal('0.0001'))) if isinstance(value, Decimal) else str(value)


def policy_table(result: dict) -> str:
    lines = ['| Policy | Groups | Holdouts predicted/eligible | Date MAE days | Holdout mean relative amount error | Rolling mean relative error | HF rolling relative error |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for p in result['policies']:
        h, r, hf = p['holdout'], p['rolling'], p['high_frequency_rolling']
        lines.append(f"| {p['policy_id']} | {p['historical_series']} | {h['predicted']}/{p['eligible_series']} | {fmt(h['date_mae_days'])} | {fmt(h['amount_mean_relative_error'])} | {fmt(r['amount_mean_relative_error'])} | {fmt(hf['amount_mean_relative_error'])} |")
    return '\n'.join(lines)


def sensitivity_report(result: dict) -> str:
    rows = result['sensitivity']
    lines = ['# Recurrence projection sensitivity', '',
             'Window: request_date through request_date + 90 days, inclusive; source occurrences only, no balance simulation.',
             'Changed means different date/direction/category/currency aggregate occurrences; series IDs alone do not count.',
             'Material means the maximum across tested policy pairs of the sum of absolute differences in total category/direction amounts exceeds 1% of requested_amount. Timing shifts alone need not be material.',
             'Only exact supplied FX dates are used. With missing rates, the home-currency-only comparison is a lower bound; foreign materiality remains unresolved.', '',
             f"Requests changed: {sum(r['any_changed'] for r in rows)}/{len(rows)}; material lower bound: {sum(r['material'] for r in rows)}; unresolved FX: {sum(r['has_unresolved_fx'] for r in rows)}.",
             f"Identity: {sum(r['identity_changed'] for r in rows)}; cadence: {sum(r['cadence_changed'] for r in rows)}; amount: {sum(r['amount_changed'] for r in rows)}; rolling spend: {sum(r['spend_rate_changed'] for r in rows)}; unaffected: {sum(not r['any_changed'] for r in rows)}.", '',
             '| Request | Maximum difference (home currency) | Fraction of request | Policy pair | Material | FX unresolved |',
             '|---|---:|---:|---|---|---|']
    for row in sorted(rows, key=lambda r: (-r['maximum_pair_relative_difference'], r['request_id'])):
        lines.append(f"| {row['request_id']} | {fmt(row['maximum_pair_difference'])} {row['home_currency']} | {fmt(row['maximum_pair_relative_difference'])} | {' / '.join(row['maximum_pair'])} | {row['material']} | {row['has_unresolved_fx']} |")
    lines += ['', 'One-factor contrasts use category/calendar/median-last-3 as the fixed experimental baseline.']
    for dimension in ['identity', 'cadence', 'amount', 'spend']:
        ratios = []
        material_count = 0
        for row in rows:
            comparisons = [c for key, c in row['comparisons_to_baseline'].items() if key.startswith(dimension + '_')]
            ratios.append(max(c['total_difference_home_currency'] for c in comparisons) / row['requested_amount'])
            material_count += any(c['material'] for c in comparisons)
        lines.append(f"- {dimension}: material in {material_count}/{len(rows)} requests; median largest one-factor difference/request = {fmt(decimal_median(ratios))}.")
    lines += ['', 'Identity has the largest median amount effect, driven by exact-description fragmentation. Family and category produce identical sample projections. Cadence changes every schedule, but often preserves the total number/amount of occurrences.',
              '', 'These are recurrence projection differences, not changes to final labeled recommendations or affordability scores.']
    return '\n'.join(lines) + '\n'


def report_text(result: dict) -> str:
    lines = ['# Phase 2 recurrence report', '',
        f"Data: {result['sample_user_count']} sample users, {result['source_event_count']} financial-event rows. Evaluation-request users were not used to select recurrence policy.",
        'All sample-user histories are backtested, including users whose final labels are confounded. No final label is a direct recurrence target, so 0/25 are directly scored against final outputs; all 25 are included for historical testing and projection sensitivity. See the per-request manifest.', '',
        '## Methods', '',
        'Twelve one-factor policies compare exact/category/family identity, four cadence methods, six amount estimators, and one 28-day spend-rate alternative. Currency always partitions identity. Category identity includes event type; family identity pools only everyday groceries/dining/transport descriptions, preserving airfare and all other descriptions. No numbers are removed.',
        'Calendar detection requires at least three consecutive months on one clamped day or month end. Otherwise it falls back to median inter-arrival. Recent median uses three intervals; mode ties use the smallest interval. Half-day interval medians round half up.',
        'Amounts use Decimal precision 40, ROUND_HALF_UP to 0.01 per projected occurrence. Rolling spend uses the last 28 days ending at the last observation, divided by 28 and scaled to inferred cadence; only <=14-day groceries/dining/transport series with 28-day history qualify, otherwise the base estimator is retained with a diagnostic.',
        'Confidence is mechanical, not probability: fewer than two observations is insufficient; fewer than three is low. High requires >=4 observations, maximum interval deviation/median <=0.10 and amount CV <=0.35. Medium allows deviation <=0.35. Staleness >2 median cycles, same-day observations, mixed categories or mixed salary descriptions make confidence low. Calendar-aligned series have zero calendar residual; raw interval MAD remains recorded. Low/insufficient series emit no occurrences.',
        'Eligibility: settled cash activity strictly known before cutoff, known nonnegative amounts; debit expense/subscription/debt_payment types, or salary/payroll/wages without speculative/temporary/final/prorated markers. Other income is excluded, not relabeled salary. Exclusion reasons are saved. Historical income projections carry explicit non-confirmation provenance.',
        'Linked graph dedup uses only visible nodes and edges at each cutoff. Components with multiple settled cash records are excluded as ambiguous, not financially resolved. Future lifecycle records cannot alter training.', '',
        '## Backtest protocol and limitations', '',
        'Hold out each sufficiently long group’s last observation; expanding rolling tests predict each observation after the first three. The cutoff is previous known observation + 1 day, never the target date. Grouping is stateless; all filtering, confidence, amounts and cadence use the training prefix only. Same-day target groups are excluded explicitly. Abstentions and short groups are counted; they are not zero errors.',
        'Raw amount MAE is reported by currency, never averaged across currency units. Relative amount errors support cross-currency comparison; zero actual amounts are excluded from relative metrics and counted. Direction/category correctness is reported but largely guaranteed by structural grouping, not a semantic classifier score.',
        'Event date is the provisional historical observation axis. Settlement must also precede the cutoff. This does not settle Phase 3 cash-flow timing. No current messages are interpreted and no future salary amendment is applied.', '',
        policy_table(result), '',
        f"Common predicted target IDs across all policies: {result['paired_common_target_count']}. Paired summaries are in phase2_recurrence_details.json; conditional errors must be read alongside coverage.", '',
        '## Selected default', '',
        f"Implemented default: {DEFAULT_POLICY.identity_method} / {DEFAULT_POLICY.cadence_method} / {DEFAULT_POLICY.amount_method}. Category identity and calendar-aware cadence are strongly supported for these visible histories: high coverage and zero next-date error; family ties category on sample projections, so the simpler category model is retained. Mean last five is moderately supported for point prediction: lower holdout and rolling relative error at identical coverage, including the high-frequency subset. It averages five observations with no learned weights or category exceptions. This does not establish a conservative essential-spending reserve. The full financial policy remains weakly identified by the 25 final labels, because none directly labels recurrence. Thresholds are provisional engineering safeguards, not statistically calibrated probabilities.", '',
        '## Outliers', '', 'Five worst distinct-target date predictions (all policies):']
    for f in result['date_outliers']:
        lines.append(f"- {f['policy_id']} {f['target_event_id']} ({f['category']}): predicted {f['predicted_date']}, actual {f['actual_date']}, error {f['date_error']} days; training descriptions {f['training_descriptions']}.")
    lines += ['', 'Five worst distinct-target relative amount predictions (all policies; comparable across currencies):']
    for f in result['amount_outliers']:
        lines.append(f"- {f['policy_id']} {f['target_event_id']} ({f['category']}): predicted {f['predicted_amount']}, actual {f['actual_amount']} {f['currency']}, absolute error {f['amount_error']}, relative error {fmt(f['relative_error'])}.")
    lines += ['', 'Cause inspection: exact-description splitting turns a regular category stream into sparse merchant observations. Three coincidentally regular visits can earn medium confidence and then fail badly; the 95-day taxi miss is such a case. Amount outliers include abrupt salary changes unknowable from the prefix and variable spending extremes. No confidence label guarantees future continuation.', '', f"Irregular/rejected baseline series: {len(result['irregular_or_rejected_series'])}. Full diagnostics, raw training event IDs, grouping examples and {len(result['missed_by_exact_grouping'])} category series completely missed by exact grouping are in phase2_recurrence_details.json.",
        '', '## Remaining boundaries', '',
        'Historical regularity does not establish future income confirmation. Final payroll markers, contract endings, salary/rent amendments and household income changes need external resolution. Low-confidence exclusion is not permission to ignore essential spending in a future safety model. Future FX selection, schedule reconciliation, event/settlement timing and same-day order remain Phase 3 questions. No simulator, capacity solver, payment logic, LLM, image extraction or output generation was built.']
    lines += ['', '## Stability across users', '']
    for comparator in [BASELINE.policy_id, 'amount_latest', 'amount_median_last_5']:
        for experiment in ['holdout', 'rolling']:
            wins = ties = losses = 0
            for user in result['per_user_amount_comparison']:
                a = user['policies']['amount_mean_last_5'][experiment]['amount_mean_relative_error']
                b = user['policies'][comparator][experiment]['amount_mean_relative_error']
                wins += a < b
                ties += a == b
                losses += a > b
            lines.append(f"- Mean-last-5 versus {comparator}, {experiment}: lower mean relative error for {wins} users, tied for {ties}, higher for {losses}.")
    lines += ['', 'Additional inspected irregular series (exact strategy, still recurring):']
    for item in result['irregular_recurring_examples'][:5]:
        lines.append(f"- {item['user_id']} {item['category']} {item['identity_key'][-1]}: {item['confidence']}, interval deviation {fmt(item['diagnostics']['maximum_interval_deviation'])}; may represent coincidental merchant visits.")
    lines += ['', 'Representative category series missed by strict identity:']
    for item in result['missed_by_exact_grouping'][:5]:
        lines.append(f"- {item['request_id']} {item['category']}: {len(item['exact_groups'])} exact-description groups versus one category series; descriptions: {', '.join(item['descriptions'])}.")
    lines += ['', 'Five largest native-unit absolute amount errors (not a cross-currency ranking of financial impact):']
    for item in result['raw_amount_outliers']:
        lines.append(f"- {item['target_event_id']} {item['policy_id']}: {item['amount_error']} {item['currency']}; actual {item['actual_amount']}, predicted {item['predicted_amount']}.")
    return '\n'.join(lines) + '\n'


def save_artifacts(result: dict, target: Path, data: Dataset) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / 'phase2_calibration_manifest.json').write_text(json_text(result['manifest']), encoding='utf-8')
    (target / 'recurrence_sensitivity.md').write_text(sensitivity_report(result), encoding='utf-8')
    (target / 'phase2_recurrence_report.md').write_text(report_text(result), encoding='utf-8')
    details = {key: value for key, value in result.items() if key not in {'folds', 'manifest'}}
    details['input_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(data.root.glob('*.csv'))}
    (target / 'phase2_recurrence_details.json').write_text(json_text(details), encoding='utf-8')
    fields = ['policy_id', 'identity_method', 'cadence_method', 'amount_method', 'spend_rate_method',
              'historical_series', 'series_evaluated', 'excluded_short_series', 'excluded_same_day_series',
              'holdout_abstentions', 'holdout_date_mae_days', 'holdout_date_median_error_days',
              'holdout_amount_mae', 'holdout_amount_median_relative_error', 'holdout_amount_mean_relative_error',
              'rolling_folds', 'rolling_predicted', 'rolling_date_mae_days', 'rolling_amount_mean_relative_error',
              'high_frequency_series_count', 'monthly_series_count', 'sample_requests_sensitive', 'notes']
    with (target / 'recurrence_calibration.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for p in result['policies']:
            h, r = p['holdout'], p['rolling']
            writer.writerow({**{key: p[key] for key in fields if key in p},
                'series_evaluated': p['eligible_series'], 'holdout_abstentions': h['abstained'],
                'holdout_date_mae_days': h['date_mae_days'], 'holdout_date_median_error_days': h['date_median_error_days'],
                'holdout_amount_mae': json.dumps(h['amount_mae_by_currency'], default=json_default, sort_keys=True),
                'holdout_amount_median_relative_error': h['amount_median_relative_error'],
                'holdout_amount_mean_relative_error': h['amount_mean_relative_error'],
                'rolling_folds': r['folds'], 'rolling_predicted': r['predicted'],
                'rolling_date_mae_days': r['date_mae_days'], 'rolling_amount_mean_relative_error': r['amount_mean_relative_error'],
                'notes': 'Native-currency MAE map; errors conditional on predictions; all final-label accuracy deferred.'})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-root', type=Path)
    parser.add_argument('--artifact-dir', type=Path, default=REPO_ROOT / 'evaluation')
    args = parser.parse_args()
    data = load_all_data(args.dataset_root)
    target = args.artifact_dir.resolve()
    if target == data.root or data.root in target.parents:
        parser.error('artifact directory must be outside the input dataset')
    with localcontext(ARITHMETIC):
        result = run_calibration(data)
        save_artifacts(result, target, data)
    print(policy_table(result))
    print(sensitivity_report(result).split('| Request')[0])
    print(f'Artifacts saved to {target}')


if __name__ == '__main__':
    main()
