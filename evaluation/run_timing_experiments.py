"""Phase 3: baseline ledgers and exogenous labeled-payment timing probes only.

No amount/date search, output recommendations, image extraction or message rules.
Run from repo root: python3 -m evaluation.run_timing_experiments
"""
import argparse
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from src.config import REPO_ROOT
from src.data.currency import CurrencyConverter, MissingExchangeRateError
from src.data.indexes import build_indexes
from src.data.loader import load_all_data
from src.forecast.preparation import prepare_forecast
from src.forecast.simulation_models import (CandidatePayment, DEFAULT_TIMING_POLICY,
    FutureEventDateSource, SameDayOrder, TimingPolicy)
from src.forecast.simulator import simulate
from src.forecast.timeline import select_fx_date
from .sample_timing_context import review_sample

D = Decimal


def json_text(value):
    def encode(item):
        if isinstance(item, (Decimal, date)):
            return str(item)
        raise TypeError(type(item).__name__)
    return json.dumps(value, default=encode, sort_keys=True, indent=2) + '\n'


def labeled_probes(request):
    """Read supplied plans and dates as experiments, never generate a plan or date.

    The earliest-date probe is a single full payment at the already-labeled date;
    it tests only safety there, never that this date is actually the earliest.
    """
    probes = {}
    if request.payment_plan not in {'', 'none'}:
        probes['supplied_plan'] = tuple(CandidatePayment(date.fromisoformat(day), D(amount),
            f'label_plan_{i}') for i, (day, amount) in enumerate(
                segment.split(':') for segment in request.payment_plan.split('|')))
    if request.earliest_date_for_full_payment is not None:
        probes['supplied_full_payment_date'] = (CandidatePayment(
            request.earliest_date_for_full_payment, request.requested_amount, 'label_full_payment'),)
    return probes


def result_summary(result):
    return {'minimum_projected_balance': result.minimum_projected_balance,
            'minimum_projected_balance_date': result.minimum_projected_balance_date,
            'first_violation_date': result.first_violation_date,
            'safe_for_supplied_flows': result.safe, 'complete': result.complete}


def compare_results(left, right):
    different_days = [a.date for a,b in zip(left.entries,right.entries)
                      if a.minimum_balance != b.minimum_balance or a.closing_balance != b.closing_balance]
    return {'changed_dates': different_days,
            'max_daily_closing_balance_difference': max(abs(a.closing_balance-b.closing_balance)
                for a,b in zip(left.entries,right.entries)),
            'max_daily_minimum_balance_difference': max(abs(a.minimum_balance-b.minimum_balance)
                for a,b in zip(left.entries,right.entries)),
            'horizon_minimum_difference': abs(left.minimum_projected_balance-right.minimum_projected_balance),
            'safety_differs': left.safe != right.safe}


def evaluate(data):
    ix = build_indexes(data)
    converter = CurrencyConverter(data.exchange_rates)
    baselines, same_day_cases, event_cases, coverage = [], [], [], []
    manifest = json.loads((REPO_ROOT / 'evaluation/phase2_calibration_manifest.json').read_text())
    prior = {item['request_id']: item for item in manifest}
    for request in data.sample_requests:
        profile = ix.profile_by_user_id[request.user_id]
        prepared = prepare_forecast(ix, request.user_id, request.request_date)
        def run(preparation, policy=DEFAULT_TIMING_POLICY, payments=()):
            return simulate(profile, request.request_date, preparation.recurring_occurrences,
                preparation.explicit_occurrences, candidate_payments=payments, timing_policy=policy,
                currency_converter=converter, unresolved_sources=preparation.unresolved_sources,
                diagnostics=preparation.diagnostics)
        base = run(prepared)
        applied = [f.occurrence for entry in base.entries for f in (*entry.credits,*entry.debits)]
        messages = ix.messages_by_user_id.get(request.user_id, ())
        images = ix.images_by_user_id.get(request.user_id, ())
        confounders = list(prior[request.request_id]['known_confounders'])
        # Every applicable message is disclosed; no hidden interpretation or exclusion.
        if messages:
            confounders.append('messages_not_semantically_applied')
        if request.spending_changes_needed not in {'', 'none'}:
            confounders.append('labeled_spending_changes_not_applied_to_baseline_probe')
        if prepared.unresolved_sources:
            confounders.append('missing_or_ambiguous_future_cashflow')
        row = {'request_id': request.request_id, 'request_date': request.request_date,
            'home_currency': profile.home_currency, 'starting_balance': profile.current_available_balance,
            'minimum_balance': profile.minimum_balance_to_keep,
            'recurring_occurrence_count': sum(f.provenance == 'recurrence_projection' for f in applied),
            'raw_recurring_occurrence_count': len(prepared.recurring_occurrences),
            'explicit_occurrence_count': sum(f.provenance != 'recurrence_projection' for f in applied),
            'pending_debit_count': sum(f.provenance == 'pending_debit' for f in applied),
            'ignored_pending_credit_count': prepared.ignored_pending_credit_count,
            'minimum_projected_balance': base.minimum_projected_balance,
            'minimum_projected_balance_date': base.minimum_projected_balance_date,
            'complete_for_supplied_structured_inputs': base.complete,
            'unresolved_sources': prepared.unresolved_sources,
            'historical_salary_projection_count': sum(f.direction == 'credit' and f.status == 'projected' for f in applied),
            'diagnostics': prepared.diagnostics,
            'known_confounders': sorted(set(confounders)),
            'message_ids': [m.message_id for m in messages],
            'image_ids_not_extracted': [i.image_id for i in images],
            'payment_option_ids_inspected': [p.payment_option_id for p in ix.payment_options_by_request_id.get(request.request_id,())]}
        row['timing_context_review'] = review_sample(request,messages,images,prepared.unresolved_sources)
        baselines.append(row)
        for flow in (*prepared.recurring_occurrences,*prepared.explicit_occurrences):
            if flow.currency != profile.home_currency:
                fx_day = select_fx_date(flow,DEFAULT_TIMING_POLICY)
                try:
                    converter.select_rate(flow.currency,profile.home_currency,fx_day)
                    exact = True
                except MissingExchangeRateError:
                    exact = False
                coverage.append({'request_id': request.request_id,'source_id':flow.source_id,
                    'date':flow.date,'fx_date':fx_day,'from_currency':flow.currency,
                    'to_currency':profile.home_currency,'exact_rate_exists':exact})
        event_policy = replace(DEFAULT_TIMING_POLICY,future_event_date_source=FutureEventDateSource.EVENT_DATE)
        event_prepared = prepare_forecast(ix,request.user_id,request.request_date,event_policy)
        alternative = run(event_prepared,event_policy)
        affected_ids = []
        for event in ix.events_by_user_id.get(request.user_id,()):
            if event.status in {'scheduled','pending'} and event.settlement_date and event.event_date != event.settlement_date:
                if (request.request_date <= event.settlement_date <= base.end_date
                    or request.request_date <= event.event_date <= base.end_date):
                    affected_ids.append(event.event_id)
        event_row = {'request_id':request.request_id,'dated_future_event_ids':affected_ids,
            'settlement_date':result_summary(base),'event_date':result_summary(alternative),
            'baseline_difference':compare_results(base,alternative),'probes':[]}
        for probe_id,payments in labeled_probes(request).items():
            cash_first = run(prepared,payments=payments)
            candidate_first = run(prepared,replace(DEFAULT_TIMING_POLICY,
                same_day_order=SameDayOrder.CANDIDATE_BEFORE_CASHFLOWS),payments)
            dates = {p.date for p in payments}
            same_day_credits = [{'date':f.date,'source_id':f.source_id,'amount':f.amount,'currency':f.currency,
                                'provenance':f.provenance} for f in applied if f.direction == 'credit' and f.date in dates]
            same_day_cases.append({'request_id':request.request_id,'probe':probe_id,
                'supplied_payments':[{'date':p.date,'amount':p.amount} for p in payments],
                'same_day_credits':same_day_credits,'cashflows_before_candidate':result_summary(cash_first),
                'candidate_before_cashflows':result_summary(candidate_first),
                'difference':compare_results(cash_first,candidate_first),
                'known_confounders':row['known_confounders'],
                'timing_context_review':row['timing_context_review'],
                'label_disambiguation':'Conditional probe only: recurrence point forecasts and unresolved evidence are not controlled label inputs.'})
            event_result = run(event_prepared,event_policy,payments)
            event_row['probes'].append({'probe':probe_id,'settlement_date':result_summary(cash_first),
                'event_date':result_summary(event_result),'difference':compare_results(cash_first,event_result)})
        event_cases.append(event_row)
    pairs = defaultdict(list)
    for rate in data.exchange_rates:
        pairs[(rate.from_currency,rate.to_currency)].append(rate)
    fx = {'date_coverage':[{'from_currency':pair[0],'to_currency':pair[1],
        'row_count':len(rows),'first_date':min(r.rate_date for r in rows),
        'last_date':max(r.rate_date for r in rows),'unique_rates':sorted({r.rate for r in rows})}
        for pair,rows in sorted(pairs.items())], 'sample_foreign_occurrences_before_reconciliation':coverage,
        'sample_users_requiring_future_fx':sorted({r['request_id'] for r in coverage}),
        'missing_exact_sample_rates':sum(not r['exact_rate_exists'] for r in coverage),
        'selected_policy':'explicit settlement FX date; projected occurrence exact date; missing rate fails',
        'evidence':'Exact rates available for visible sample projections; all supplied pairs are constant. No evidence for unsupplied future dates.'}
    same_ids = sorted({c['request_id'] for c in same_day_cases if c['difference']['changed_dates']})
    same_flips = sorted({c['request_id'] for c in same_day_cases if c['difference']['safety_differs']})
    supporting_ids = sorted({c['request_id'] for c in same_day_cases
        if c['difference']['safety_differs'] and c['cashflows_before_candidate']['safe_for_supplied_flows']
        and c['timing_context_review']['conditional_timing_support_eligible']})
    event_ids = sorted({c['request_id'] for c in event_cases if c['baseline_difference']['changed_dates']})
    event_flips = sorted({c['request_id'] for c in event_cases if any(p['difference']['safety_differs'] for p in c['probes'])})
    artifact = {'scope':'Phase 3: supplied-flow safety probes, not affordability decisions or earliest-date validation',
        'sample_requests':len(baselines),'horizon_calendar_dates':91,
        'recurrence_policy':'category / calendar_aware / mean_last_5 (provisional)',
        'same_day':{'policies':[p.value for p in SameDayOrder], 'probe_count':len(same_day_cases),
            'safe_probe_count_cashflows_first':sum(c['cashflows_before_candidate']['safe_for_supplied_flows'] for c in same_day_cases),
            'safe_probe_count_candidate_first':sum(c['candidate_before_cashflows']['safe_for_supplied_flows'] for c in same_day_cases),
            'requests_with_same_day_credit':sorted({c['request_id'] for c in same_day_cases if c['same_day_credits']}),
            'numerically_sensitive_request_ids':same_ids,'numerically_sensitive_count':len(same_ids),
            'conditional_safety_flip_request_ids':same_flips,'conditional_safety_flip_count':len(same_flips),
            'conditionally_supporting_request_ids':supporting_ids,
            'conditionally_supporting_count':len(supporting_ids),
            'uniquely_identifying_labels_count':0,'selected_default':DEFAULT_TIMING_POLICY.same_day_order.value,
            'strength_of_evidence':'partially supported under provisional recurrence; not uniquely disambiguated', 'cases':same_day_cases},
        'event_date':{'policies':[p.value for p in FutureEventDateSource],
            'visible_future_events_with_different_dates':sum(len(c['dated_future_event_ids']) for c in event_cases),
            'numerically_sensitive_request_ids':event_ids,'numerically_sensitive_count':len(event_ids),
            'conditional_label_probe_safety_flip_request_ids':event_flips,
            'conditional_label_probe_safety_flip_count':len(event_flips),
            'labels_establishing_policy_count':0,'selected_default':DEFAULT_TIMING_POLICY.future_event_date_source.value,
            'strength_of_evidence':'not disambiguated by visible labels; settlement aligns with stated cash/FX semantics',
            'cases':event_cases},'fx':fx,
        'unresolved_ambiguity':['Point recurrence predictions are not confirmed future income or conservative essential-spend reserves.',
            'Sample message amendments and image amounts are not interpreted; confounders are enumerated for every case.',
            'A safe supplied-date probe does not prove an earliest date; an unsafe one may reflect other missing semantics.',
            'Candidate/normal ordering changes intraday minima, not daily closing balances.',
            'Normal cashflows use credits then aggregated debits; internal transaction order is not labeled.',
            'Pending debit reservation timing remains provisional; event-date mode reserves overdue authorizations immediately.']}
    return artifact,baselines


def report(artifact,baselines):
    same,event,fx=artifact['same_day'],artifact['event_date'],artifact['fx']
    lines=['# Phase 3 timing experiments','',
        'Reproduce: `python3 -m evaluation.run_timing_experiments`. All amounts remain Decimal; comparisons are within each home currency. No cross-currency ranking of raw amounts.', '',
        '## Method','',
        'All 25 samples are included. Read supplied payment plans and supplied earliest full-payment dates as exogenous probes. No capacity or date search, recommendation, plan generation, spending search, message interpretation or image extraction is implemented. Baseline diagnostics contain no candidate payments. Labeled spending changes are disclosed but not applied to timing probes.', '',
        'The same production simulator runs all variants. The horizon contains 91 dates (D through D+90). Opening balance and credit/debit/candidate block boundaries count for safety. Normal cashflows apply aggregate credits then debits, independent of CSV order. Missing future amounts produce incomplete known-flow diagnostics and never a safe result.', '',
        '## Same-day ordering','',
        f"Supplied-probe safety passes: cashflows first {same['safe_probe_count_cashflows_first']}/{same['probe_count']}; candidate first {same['safe_probe_count_candidate_first']}/{same['probe_count']}. These are conditional safety observations, not final-label accuracy.", '',
        f"{same['probe_count']} supplied probes; {len(same['requests_with_same_day_credit'])} requests have credits on probe dates. Numerically sensitive: {same['numerically_sensitive_count']} ({', '.join(same['numerically_sensitive_request_ids']) or 'none'}). Conditional horizon-safety flips: {same['conditional_safety_flip_count']} ({', '.join(same['conditional_safety_flip_request_ids']) or 'none'}).", '',
        '| Request / probe | Minimum: cashflows first | Minimum: candidate first | Largest daily minimum difference | Safety flips |',
        '|---|---:|---:|---:|---|']
    for case in same['cases']:
        if case['difference']['changed_dates']:
            lines.append(f"| {case['request_id']} / {case['probe']} | {case['cashflows_before_candidate']['minimum_projected_balance']} | {case['candidate_before_cashflows']['minimum_projected_balance']} | {case['difference']['max_daily_minimum_balance_difference']} | {case['difference']['safety_differs']} |")
    lines += ['', 'Daily closing balance differences are exactly zero for ordering alternatives. These are conditional forecast differences, not end-to-end label scores. ' + str(same['conditionally_supporting_count']) + ' requests (' + ', '.join(same['conditionally_supporting_request_ids']) + ') conditionally favor cashflows first after reviewing message facts and excluding unextracted amounts/unapplied spending changes. The other safety flips have explicit blockers listed below. Zero labels uniquely establish the policy independent of provisional recurrence. Default: cashflows before candidate. Evidence: **partially supported**, not uniquely disambiguated. It avoids declaring a within-day debit before a same-day credit when only dates are supplied; intraday bank ordering is still unknown.', '',
        '## Event date versus settlement date','',
        f"{event['visible_future_events_with_different_dates']} visible pending/scheduled rows have differing dates, including ignored or missing-amount rows. {event['numerically_sensitive_count']} baseline ledgers change: {', '.join(event['numerically_sensitive_request_ids'])}. Conditional supplied-probe safety flips: {event['conditional_label_probe_safety_flip_count']} ({', '.join(event['conditional_label_probe_safety_flip_request_ids']) or 'none'}).", '',
        '| Request | Relevant event IDs | Largest closing-balance difference | Horizon minimum difference |',
        '|---|---|---:|---:|']
    for case in event['cases']:
        if case['dated_future_event_ids']:
            lines.append(f"| {case['request_id']} | {', '.join(case['dated_future_event_ids'])} | {case['baseline_difference']['max_daily_closing_balance_difference']} | {case['baseline_difference']['horizon_minimum_difference']} |")
    lines += ['', 'Default: settlement date; absent settlement uses event date, overdue debit reserves on D. This follows cash settlement semantics, but visible labels do not resolve debit authorization reservation timing. FX continues to use explicit settlement date under either timing flag, isolating cash timing from rate valuation. Zero labels establish a timing winner.', '', '## FX','',
        '| Pair | Rows | First date | Last date | Unique rates |','|---|---:|---|---|---|']
    for pair in fx['date_coverage']:
        lines.append(f"| {pair['from_currency']} → {pair['to_currency']} | {pair['row_count']} | {pair['first_date']} | {pair['last_date']} | {', '.join(map(str,pair['unique_rates']))} |")
    lines += ['',f"Future foreign-currency projections are needed for {', '.join(fx['sample_users_requiring_future_fx'])}; missing exact rates: {fx['missing_exact_sample_rates']}. All pair rates are constant in the provided file, so these samples cannot distinguish future FX fallback strategies. No fallback is implemented.", '', '## Baseline diagnostics','',
        '| Request | Currency | Starting balance | Floor | Recurring / explicit / pending | Minimum known-flow balance | Date | Complete structured inputs |',
        '|---|---|---:|---:|---|---:|---|---|']
    for row in baselines:
        lines.append(f"| {row['request_id']} | {row['home_currency']} | {row['starting_balance']} | {row['minimum_balance']} | {row['recurring_occurrence_count']} / {row['explicit_occurrence_count']} / {row['pending_debit_count']} | {row['minimum_projected_balance']} | {row['minimum_projected_balance_date']} | {row['complete_for_supplied_structured_inputs']} |")
    lines += ['', 'Completeness covers supplied structured future amounts only, not semantic completeness of messages or images. request_16 (event_1442) and request_20 (event_1786) have unknown future debit amounts; their minima exclude those unknown values and are conditional, never certified safe. Source salary projections remain predictions, not confirmation. The later settled final-payroll marker event_390 suppresses older salary continuation for request_05, independently of the unchanged Phase 2 estimator. Contract termination, changed/delayed salaries, leave, rent changes and unspecified childcare require later evidence resolution.', '', '## Confounders inspected','',
        '| Request | Messages | Images | Known confounders |','|---|---|---|---|']
    for row in baselines:
        lines.append(f"| {row['request_id']} | {', '.join(row['message_ids']) or 'none'} | {', '.join(row['image_ids_not_extracted']) or 'none'} | {', '.join(row['known_confounders']) or 'none identified'} |")
    lines += ['', '## Timing-context review', '', '| Request | Conditional support eligible | Blockers | Reviewed message facts |', '|---|---|---|---|']
    for row in baselines:
        review=row['timing_context_review']
        lines.append(f"| {row['request_id']} | {review['conditional_timing_support_eligible']} | {', '.join(review['timing_probe_blockers']) or 'none'} | {'; '.join(r['reason'] for r in review['message_reviews']) or 'no messages'} |")
    lines += ['', '## Limits and architecture boundary','',
        'Architecture §21 previously asked for safe-amount, earliest-date, status and plan match metrics. Those need Phase 4+ decisions. The Phase 3 clarification limits this experiment to supplied-flow traces and safety probes. No labels are hardcoded in production. Future evidence amendments can enter as explicit confirmed occurrences after reconciliation; no sample-specific override rules were needed to measure conditional sensitivity.', '',
        'Low/insufficient recurrence stays omitted. The minimum is the earliest occurrence of the lowest opening/intermediate/closing balance. Equal-to-floor is safe only for complete inputs. Spending effects are supplied externally, must target recurring debits and respect protected/preference/flexibility/floor rules; they modify actual debits without creating savings credits.', '']
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-root',type=Path)
    parser.add_argument('--output-dir',type=Path,default=REPO_ROOT/'evaluation')
    args=parser.parse_args()
    data=load_all_data(args.dataset_root)
    artifact,baselines=evaluate(data)
    artifact['input_sha256']={path.name:hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(data.root.glob('*.csv'))}
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/'phase3_timing_experiments.json').write_text(json_text(artifact),encoding='utf-8')
    (args.output_dir/'phase3_simulation_diagnostics.json').write_text(json_text(baselines),encoding='utf-8')
    (args.output_dir/'phase3_timing_report.md').write_text(report(artifact,baselines),encoding='utf-8')
    print(f"Sample baseline diagnostics: {len(baselines)}; incomplete structured inputs: {sum(not r['complete_for_supplied_structured_inputs'] for r in baselines)}")
    print(f"Same-day probes: {artifact['same_day']['probe_count']}; numerically sensitive requests: {artifact['same_day']['numerically_sensitive_count']}; conditional safety flips: {artifact['same_day']['conditional_safety_flip_count']}")
    print(f"Different-date future events: {artifact['event_date']['visible_future_events_with_different_dates']}; changed baseline requests: {artifact['event_date']['numerically_sensitive_count']}; conditional label-probe safety flips: {artifact['event_date']['conditional_label_probe_safety_flip_count']}")
    print(f"Missing exact sample FX rates: {artifact['fx']['missing_exact_sample_rates']}")
    print('Wrote phase3_timing_experiments.json, phase3_simulation_diagnostics.json, phase3_timing_report.md')


if __name__ == '__main__':
    main()
