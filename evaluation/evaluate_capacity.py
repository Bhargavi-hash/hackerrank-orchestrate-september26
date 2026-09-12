"""Phase 4 sample capacity regression only; never generates submission output."""
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal, localcontext
import csv
import hashlib
import json
from pathlib import Path
from time import perf_counter_ns

from src.config import REPO_ROOT
from src.data.currency import CurrencyConverter
from src.data.indexes import build_indexes
from src.data.loader import Dataset, load_all_data
from src.forecast.preparation import prepare_forecast
from src.forecast.recurrence import ARITHMETIC, decimal_median
from src.forecast.recurrence_models import DEFAULT_POLICY
from src.forecast.simulation_models import CashFlowOccurrence, PreparedForecast, CandidatePayment
from src.forecast.simulator import simulate
from src.models.profile import FinancialProfile
from src.planning.capacity import evaluate_capacity, prepare_capacity
from .sample_timing_context import MESSAGE_REVIEWS

D=Decimal
METHODS=('mean_last_5','median_last_3','latest')
COLUMNS=('request_id','currency','requested_amount','predicted_safe_amount','expected_safe_amount',
    'safe_amount_abs_error','safe_amount_relative_error','safe_amount_error_over_requested_amount',
    'predicted_earliest_date','expected_earliest_date','earliest_date_error_days',
    'baseline_complete','likely_mismatch_cause','notes')


def json_text(value: object) -> str:
    def encode(item):
        if isinstance(item,(date,Decimal)):
            return str(item)
        raise TypeError(type(item).__name__)
    return json.dumps(value,default=encode,indent=2,sort_keys=True)+'\n'


def mean(values) -> Decimal | None:
    values=tuple(values)
    with localcontext(ARITHMETIC):
        return sum(values,D(0))/D(len(values)) if values else None


def median(values) -> Decimal | None:
    values=tuple(values)
    return decimal_median(values) if values else None


def compare_row(request, profile, result) -> dict:
    with localcontext(ARITHMETIC):
        error=abs(result.amount_safe_to_pay-request.amount_safe_to_pay)
        relative=error/abs(request.amount_safe_to_pay) if request.amount_safe_to_pay else None
        normalized=error/request.requested_amount if request.requested_amount else None
    predicted,expected=result.earliest_date_for_full_payment,request.earliest_date_for_full_payment
    return {'request_id':request.request_id,'currency':profile.home_currency,
        'requested_amount':request.requested_amount,'predicted_safe_amount':result.amount_safe_to_pay,
        'expected_safe_amount':request.amount_safe_to_pay,'safe_amount_abs_error':error,
        'safe_amount_relative_error':relative,'safe_amount_error_over_requested_amount':normalized,
        'predicted_earliest_date':predicted,'expected_earliest_date':expected,
        'earliest_date_error_days':abs((predicted-expected).days) if predicted and expected else None,
        'baseline_complete':result.baseline_complete}


def summarize(rows) -> dict:
    currencies=defaultdict(list)
    for row in rows:
        currencies[row['currency']].append(row['safe_amount_abs_error'])
    paired=[row['earliest_date_error_days'] for row in rows if row['earliest_date_error_days'] is not None]
    present_mismatch=sum((r['predicted_earliest_date'] is None)!=(r['expected_earliest_date'] is None) for r in rows)
    relatives=[r['safe_amount_relative_error'] for r in rows if r['safe_amount_relative_error'] is not None]
    normalized=[r['safe_amount_error_over_requested_amount'] for r in rows if r['safe_amount_error_over_requested_amount'] is not None]
    return {'sample_count':len(rows),'safe_amount_exact_matches':sum(r['safe_amount_abs_error']==0 for r in rows),
        'safe_amount_error_by_currency':{currency:{'count':len(errors),'mae':mean(errors),
            'median_absolute_error':median(errors),'maximum_absolute_error':max(errors)}
            for currency,errors in sorted(currencies.items())},
        'safe_amount_median_relative_error':median(relatives),
        'safe_amount_mean_relative_error':mean(relatives),'relative_error_count':len(relatives),
        'safe_amount_mean_error_over_requested_amount':mean(normalized),
        'safe_amount_median_error_over_requested_amount':median(normalized),
        'earliest_date_exact_matches':sum(r['predicted_earliest_date']==r['expected_earliest_date'] for r in rows),
        'earliest_date_both_missing':sum(r['predicted_earliest_date'] is None and r['expected_earliest_date'] is None for r in rows),
        'earliest_date_present_pair_count':len(paired),
        'earliest_date_within_1_day_present_pairs':sum(e<=1 for e in paired),
        'earliest_date_within_3_days_present_pairs':sum(e<=3 for e in paired),
        'earliest_date_within_7_days_present_pairs':sum(e<=7 for e in paired),
        'earliest_date_missing_present_mismatches':present_mismatch,
        'earliest_date_median_absolute_error_days':median(map(D,paired)),
        'earliest_date_maximum_absolute_error_days':max(paired) if paired else None}


def date_error_key(row):
    """For alternative comparisons: presence mismatch first, then finite day error.

    No invented numerical day penalty for a missing date. Both blank matches get
    (0,0), paired dates (0,absolute error), presence mismatches (1,0).
    """
    mismatch=(row['predicted_earliest_date'] is None)!=(row['expected_earliest_date'] is None)
    return int(mismatch),row['earliest_date_error_days'] or 0


def compare_estimators(base, alternative) -> dict:
    by_id={r['request_id']:r for r in alternative}
    buckets={name:[] for name in ('safe_improved','safe_worsened','safe_tied',
        'date_improved','date_worsened','date_tied','both_fields_no_worse_one_better',
        'both_fields_no_better_one_worse','tradeoff','both_tied')}
    for a in base:
        b=by_id[a['request_id']]
        safe=(b['safe_amount_abs_error']>a['safe_amount_abs_error'])-(b['safe_amount_abs_error']<a['safe_amount_abs_error'])
        dates=(date_error_key(b)>date_error_key(a))-(date_error_key(b)<date_error_key(a))
        buckets['safe_'+{-1:'improved',0:'tied',1:'worsened'}[safe]].append(a['request_id'])
        buckets['date_'+{-1:'improved',0:'tied',1:'worsened'}[dates]].append(a['request_id'])
        if safe==dates==0:
            group='both_tied'
        elif safe<=0 and dates<=0:
            group='both_fields_no_worse_one_better'
        elif safe>=0 and dates>=0:
            group='both_fields_no_better_one_worse'
        else:
            group='tradeoff'
        buckets[group].append(a['request_id'])
    return {key:{'count':len(ids),'request_ids':ids} for key,ids in buckets.items()}


def mismatch_context(request, row, variants, ix, forecast):
    """Evaluation hypotheses with source references, never production overrides."""
    if row['safe_amount_abs_error']==0 and row['predicted_earliest_date']==row['expected_earliest_date']:
        return [],['Both capacity fields match; this does not validate all upstream evidence.']
    causes,notes=[],[]
    images=ix.images_by_user_id.get(request.user_id,())
    if images:
        causes.append('missing_image_amount')
        notes.append('Unextracted image-linked amounts: '+', '.join(f'{i.image_id}/{i.related_event_id}' for i in images)+'.')
    messages=ix.messages_by_user_id.get(request.user_id,())
    for message in messages:
        covered,reason=MESSAGE_REVIEWS.get(message.message_id,(False,'Unreviewed message.'))
        if not covered:
            causes.append('missing_message_amendment')
            notes.append(f'{message.message_id}: {reason}')
    sensitive=[method for method,alternative in variants.items() if method!=DEFAULT_POLICY.amount_method
        and (alternative['predicted_safe_amount']!=row['predicted_safe_amount']
             or alternative['predicted_earliest_date']!=row['predicted_earliest_date'])]
    if sensitive:
        causes.append('recurrence_amount')
        notes.append('Capacity changes under '+', '.join(sensitive)+'; sensitivity is not proof of the correct estimator.')
    income=[e for e in ix.events_by_user_id[request.user_id] if e.direction=='credit' and e.category=='salary' and e.status=='settled']
    predicted_income=[f for f in forecast.recurring_occurrences if f.direction=='credit']
    if income and not predicted_income:
        causes.append('recurrence_identity')
        notes.append('No recurring income survives history/continuation gates. Review source eligibility; do not admit speculative income to fit labels.')
    if forecast.unresolved_sources:
        notes.append('Incomplete future forecast uses terminal zero capacity and blank date.')
    if not causes:
        causes.append('unknown')
        notes.append('No isolated upstream cause established by the tested alternatives.')
    notes.append('Deadline, payment preferences and optional spending changes cannot explain capacity differences: they are deliberately excluded.')
    return list(dict.fromkeys(causes)),notes


def formula_counterexample():
    start=date(2025,1,1)
    profile=FinancialProfile('example','USD',D('100'),D('20'),(),frozenset(),frozenset(),frozenset(),frozenset(),None)
    credit=CashFlowOccurrence('confirmed_credit','example',start,D('100'),'USD','credit','salary',
                              'structured_example','confirmed','income')
    ctx=prepare_capacity(profile,start,PreparedForecast((),(credit,),(),(),0))
    result=evaluate_capacity(ctx,D('200'))
    return {'opening_balance':D('100'),'today_credit':D('100'),'floor':D('20'),
        'all_checkpoint_headroom':result.all_checkpoint_headroom,'payment_affected_headroom':result.minimum_headroom,
        'verified_capacity':result.amount_safe_to_pay,'next_cent_unsafe':result.maximality_verified,
        'user_resolution':'Use payment-affected checkpoints for the actual maximum'}


def evaluate_samples(data: Dataset, methods=METHODS):
    ix=build_indexes(data)
    converter=CurrencyConverter(data.exchange_rates)
    rows_by_method={method:[] for method in methods}
    details={}
    runtimes={method:{'preparation_ns':0,'capacity_ns':0} for method in methods}
    for request in data.sample_requests:
        variants={}
        for method in methods:
            started=perf_counter_ns()
            policy=replace(DEFAULT_POLICY,amount_method=method,policy_id=f'phase4_{method}')
            prepared=prepare_forecast(ix,request.user_id,request.request_date,recurrence_policy=policy)
            profile=ix.profile_by_user_id[request.user_id]
            ctx=prepare_capacity(profile,request.request_date,prepared,converter)
            ready=perf_counter_ns()
            result=evaluate_capacity(ctx,request.requested_amount)
            done=perf_counter_ns()
            runtimes[method]['preparation_ns']+=ready-started
            runtimes[method]['capacity_ns']+=done-ready
            row=compare_row(request,profile,result)
            rows_by_method[method].append(row)
            variants[method]=row
            if method==DEFAULT_POLICY.amount_method:
                baseline_entry=next(e for e in ctx.baseline.entries if e.date==ctx.baseline.minimum_projected_balance_date)
                details[request.request_id]={'result':asdict(result),'baseline_minimum_entry':asdict(baseline_entry),
                    'baseline_minimum_balance':ctx.baseline.minimum_projected_balance,
                    'baseline_first_violation_date':ctx.baseline.first_violation_date,
                    'request_date':request.request_date,'forecast_end_date':ctx.baseline.end_date,
                    'desired_completion_date_not_used':request.desired_completion_date,
                    'image_ids':[i.image_id for i in ix.images_by_user_id.get(request.user_id,())],
                    'message_ids':[m.message_id for m in ix.messages_by_user_id.get(request.user_id,())],
                    'payment_option_ids_not_used':[o.payment_option_id for o in ix.payment_options_by_request_id.get(request.request_id,())],
                    'projected_series':[{'series_id':f.series_id,'direction':f.direction,'category':f.category,
                        'amount':f.amount,'currency':f.currency,'source_event_ids':f.source_event_ids}
                        for i,f in enumerate(prepared.recurring_occurrences)
                        if f.series_id not in {x.series_id for x in prepared.recurring_occurrences[:i]}]}
                label_probe=simulate(profile,request.request_date,prepared.recurring_occurrences,
                    prepared.explicit_occurrences,candidate_payments=(CandidatePayment(request.request_date,
                        request.amount_safe_to_pay,'supplied_capacity_label_probe'),),currency_converter=converter,
                    unresolved_sources=prepared.unresolved_sources)
                details[request.request_id]['supplied_safe_amount_probe']={
                    'safe_on_current_forecast':label_probe.safe,'complete':label_probe.complete,
                    'minimum_balance':label_probe.minimum_projected_balance,
                    'first_violation_date':label_probe.first_violation_date,
                    'floor':profile.minimum_balance_to_keep}
                base_forecast=prepared
        base=variants[DEFAULT_POLICY.amount_method]
        causes,notes=mismatch_context(request,base,variants,ix,base_forecast)
        base.update(likely_mismatch_cause='|'.join(causes) or 'none',notes=' '.join(notes))
        details[request.request_id]['likely_causes']=causes
        details[request.request_id]['cause_notes']=notes
        details[request.request_id]['recurrence_alternatives']=variants
    baseline=rows_by_method[DEFAULT_POLICY.amount_method]
    summaries={method:summarize(rows) for method,rows in rows_by_method.items()}
    comparisons={method:compare_estimators(baseline,rows) for method,rows in rows_by_method.items() if method!=DEFAULT_POLICY.amount_method}
    cause_counts=Counter(cause for row in baseline for cause in row['likely_mismatch_cause'].split('|') if cause!='none')
    with localcontext(ARITHMETIC):
        timings={method:{'preparation_seconds':D(v['preparation_ns'])/D(10**9),
            'capacity_seconds':D(v['capacity_ns'])/D(10**9),
            'total_seconds':D(v['preparation_ns']+v['capacity_ns'])/D(10**9),
            'average_total_seconds_per_request':D(v['preparation_ns']+v['capacity_ns'])/D(10**9)/D(len(baseline)),
            'estimated_250_seconds_not_measured':D(v['preparation_ns']+v['capacity_ns'])/D(10**9)*D(250)/D(len(baseline))}
            for method,v in runtimes.items()}
    return baseline,{'checkpoint_clarification_changes_sample_headroom_count':sum(
        item['result']['minimum_headroom'] != item['result']['all_checkpoint_headroom'] for item in details.values()),
        'supplied_safe_amount_labels_safe_on_current_forecast_count':sum(item['supplied_safe_amount_probe']['safe_on_current_forecast'] for item in details.values()),
        'metrics_by_estimator':summaries,'estimator_comparisons':comparisons,
        'cause_counts_nonexclusive':dict(sorted(cause_counts.items())),
        'formula_clarification':formula_counterexample(),'requests':details,'performance':timings,
        'selected_default_unchanged':DEFAULT_POLICY.amount_method,
        'metric_definitions':{'safe_relative_error':'absolute error / nonzero labeled safe amount',
            'normalized_error':'absolute safe-amount error / positive requested amount',
            'date_exact':'includes both missing; no arbitrary day penalty for presence mismatch',
            'date_tolerances':'paired present dates only, inclusive tolerance; includes exact paired matches',
            'estimator_date_comparison':'presence-match first, then finite absolute day error',
            'row_improvement':'both capacity errors no worse and at least one better; tradeoffs reported separately'},
        'monotonicity':'With exogenous fixed flows and a fixed request horizon, delaying a fixed payment cannot lower any checkpoint balance. Recurring obligations do not invalidate this. Search remains sequential; no binary search.'}


def fmt(value):
    if value is None:
        return '—'
    if isinstance(value,Decimal):
        return f'{value:.6f}'.rstrip('0').rstrip('.') or '0'
    return str(value)


def make_report(rows,details):
    stats=details['metrics_by_estimator'][DEFAULT_POLICY.amount_method]
    lines=['# Phase 4 capacity regression','',
        'Reproduce: `python3 -m evaluation.evaluate_capacity`. Only the 25 supplied sample rows are evaluated; no predictions for the 250 unlabeled requests or final output CSV are generated.', '',
        '## Algorithm and scope','',
        'Prepare recurrence and explicit occurrences once per request/policy; build one unchanged baseline. Calculate the minimum headroom over the simulator checkpoints affected by a request-date payment. Earlier checkpoints must separately be safe. Clamp to [0, requested amount], round down to 0.01 (same convention for every supplied currency), and independently resimulate the amount and the next cent when within the requested cap. Missing future debit uncertainty yields zero and no provable full-payment date. A zero result on an already-unsafe baseline is a terminal capacity bound, not a claim that the baseline is safe.', '',
        'Search every calendar date sequentially from D through D+90 inclusive, preserving the original request-centered 91-date forecast. No rolling extension, deadline restriction, payment preference filter, spending changes, recommendation or plan ranking. The full-payment probe uses the exact requested amount. Phase 3 timing and Phase 2 recurrence defaults are unchanged.', '',
        '## Architecture clarification','',
        'The literal all-checkpoint formula conflicted with maximality under cashflows-first timing: opening 100, today credit 100, floor 20 gives all-checkpoint headroom 80, but payment 180 is safe. The user explicitly selected payment-affected checkpoints for the actual maximum. The implementation reads the simulator candidate-payment checkpoint marker rather than redefining order. The saved counterexample independently verifies 180 safe and 180.01 unsafe.', '',
        'The official “next 90 days” wording and architecture §§22/24 anchor the forecast at the request. No text requires extending it 90 days beyond a later payment. Within that fixed horizon, delaying a payment leaves earlier balances higher and later balances equal. Therefore safe(d) implies safe(d+1) for these exogenous flows—even with recurring obligations. No genuine non-monotonic counterexample exists under current semantics; tests verify this and the implementation still scans dates sequentially.', '',
        '## Safe-amount metrics','',f"Exact matches: **{stats['safe_amount_exact_matches']}/{len(rows)}**.", '',
        '| Currency | Rows | MAE | Median absolute error | Maximum absolute error |','|---|---:|---:|---:|---:|']
    for currency,values in stats['safe_amount_error_by_currency'].items():
        lines.append(f"| {currency} | {values['count']} | {fmt(values['mae'])} | {fmt(values['median_absolute_error'])} | {fmt(values['maximum_absolute_error'])} |")
    lines += ['',f"Median relative error (absolute error / labeled nonzero safe amount): {fmt(stats['safe_amount_median_relative_error'])}; mean: {fmt(stats['safe_amount_mean_relative_error'])}; denominator: {stats['relative_error_count']} rows. Mean error normalized by requested amount: {fmt(stats['safe_amount_mean_error_over_requested_amount'])}. Raw errors in different currencies are never averaged together.", '',
        '## Earliest-date metrics','',
        f"Exact matches: **{stats['earliest_date_exact_matches']}/{len(rows)}**, including {stats['earliest_date_both_missing']} both-blank matches. Paired present dates: {stats['earliest_date_present_pair_count']}.", '',
        f"Within 1 / 3 / 7 days among paired present dates: **{stats['earliest_date_within_1_day_present_pairs']} / {stats['earliest_date_within_3_days_present_pairs']} / {stats['earliest_date_within_7_days_present_pairs']}**. Missing/present mismatches: **{stats['earliest_date_missing_present_mismatches']}**. Median / maximum absolute paired date error: **{fmt(stats['earliest_date_median_absolute_error_days'])} / {fmt(stats['earliest_date_maximum_absolute_error_days'])} days**.", '',
        '## Every sample result','',
        '| Request | Currency | Predicted safe | Labeled safe | Predicted full date | Labeled full date | Complete baseline | Likely causes |',
        '|---|---|---:|---:|---|---|---|---|']
    for row in rows:
        lines.append(f"| {row['request_id']} | {row['currency']} | {row['predicted_safe_amount']} | {row['expected_safe_amount']} | {fmt(row['predicted_earliest_date'])} | {fmt(row['expected_earliest_date'])} | {row['baseline_complete']} | {row['likely_mismatch_cause'].replace('|', ', ')} |")
    lines += ['', '## Mismatch analysis','',
        f"The approved checkpoint clarification changes headroom for {details['checkpoint_clarification_changes_sample_headroom_count']} of these 25 samples. It therefore does not explain the zero exact safe-amount matches. Independently replaying labeled safe amounts succeeds on only {details['supplied_safe_amount_labels_safe_on_current_forecast_count']}/25 current forecasts; the remaining rows fail or are incomplete. This directly demonstrates upstream forecast disagreement, rather than a capacity formula fitted to labels. Source rows at each limiting checkpoint and every date-search probe are saved in the details artifact.", '',
        'Causes are hypotheses grounded in visible source rows and measured estimator sensitivity, not confirmed semantic resolutions. Counts are nonexclusive: '+', '.join(f'{key}={count}' for key,count in details['cause_counts_nonexclusive'].items())+'.', '']
    for row in rows:
        if row['likely_mismatch_cause']!='none':
            lines.append(f"- **{row['request_id']}**: {row['notes']}")
    lines += ['', 'Largest mismatches by request-normalized error (not mixed-currency native units):','']
    for row in sorted(rows,key=lambda r:r['safe_amount_error_over_requested_amount'] or D(0),reverse=True)[:5]:
        lines.append(f"- {row['request_id']}: error {row['safe_amount_abs_error']} {row['currency']}; {fmt(row['safe_amount_error_over_requested_amount'])} of requested amount.")
    lines += ['', '## Recurrence downstream comparison','',
        'All 25 requests are rerun with only the recurrence amount estimator changed. This includes every amount-sensitive mismatch and avoids cherry-picking improvements. Message/image inputs and timing remain unchanged.', '',
        '| Estimator | Safe exact | Mean error / requested | Date exact | Presence mismatches |',
        '|---|---:|---:|---:|---:|']
    for method,summary in details['metrics_by_estimator'].items():
        lines.append(f"| {method} | {summary['safe_amount_exact_matches']} | {fmt(summary['safe_amount_mean_error_over_requested_amount'])} | {summary['earliest_date_exact_matches']} | {summary['earliest_date_missing_present_mismatches']} |")
    lines += ['', '| Alternative vs mean-5 | Safe improve / worsen / tie | Date improve / worsen / tie | Both no worse, one better | Both no better, one worse | Tradeoffs |',
              '|---|---|---|---:|---:|---:|']
    for method,c in details['estimator_comparisons'].items():
        lines.append(f"| {method} | {c['safe_improved']['count']} / {c['safe_worsened']['count']} / {c['safe_tied']['count']} | {c['date_improved']['count']} / {c['date_worsened']['count']} / {c['date_tied']['count']} | {c['both_fields_no_worse_one_better']['count']} | {c['both_fields_no_better_one_worse']['count']} | {c['tradeoff']['count']} |")
    lines += ['', 'Mean-last-5 remains defensible as the provisional default: it has the lowest mean request-normalized safe-amount error of these three estimators. Median-last-3 improves more individual safe amounts but worsens others, and both alternatives gain only one exact date. Neither alternative dominates across the two fields and all rows. Zero exact safe amounts under all three policies indicates that changing just this estimator does not reproduce benchmark capacity semantics. Historical point-prediction support is separate from capacity calibration; unresolved evidence remains a confounder. No request-specific estimator switch is made. Detailed per-request alternatives and improvement/worsening IDs are saved in phase4_capacity_details.json.', '',
        '## Performance','',
        'Measured with perf_counter_ns; times include forecast preparation and capacity simulations, exclude shared CSV loading/index construction and artifact writing. Timing measurements vary by run; financial results do not.', '',
        '| Estimator | Preparation seconds | Capacity seconds | Total, 25 requests | Average/request | Linear estimate, 250 (not measured) |',
        '|---|---:|---:|---:|---:|---:|']
    for method,times in details['performance'].items():
        lines.append(f"| {method} | {fmt(times['preparation_seconds'])} | {fmt(times['capacity_seconds'])} | {fmt(times['total_seconds'])} | {fmt(times['average_total_seconds_per_request'])} | {fmt(times['estimated_250_seconds_not_measured'])} |")
    lines += ['', '## Remaining boundaries','',
        'Capacity mismatches cannot be fixed by Phase 5 payment selection, deadline eligibility or preference handling: those are intentionally independent. Upstream recurrence/confirmation questions need later calibration/evidence resolution, and image-backed amounts need the later extraction phase. Unknown future amounts for requests 16 and 20 deliberately remain terminal. Missing historical amounts can also affect recurrence even when baseline_complete is true. Salary/rent amendments and unspecified childcare remain unapplied. No model calls or inferred amounts are introduced.', '',
        'The Phase 3 explicit-event, pending-debit and exact-FX rules remain unchanged. This run does not isolate every possible identity, cadence or timing error; residual mismatch causes are hypotheses, not proof that the capacity arithmetic is wrong. Partial-payment composability remains documented in architecture, but no partial plan is constructed here.', '']
    return '\n'.join(lines)


def write_artifacts(output_dir: Path, rows, details):
    output_dir.mkdir(parents=True,exist_ok=True)
    with (output_dir/'phase4_capacity_results.csv').open('w',encoding='utf-8',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=COLUMNS,lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    (output_dir/'phase4_capacity_details.json').write_text(json_text(details),encoding='utf-8')
    (output_dir/'phase4_capacity_report.md').write_text(make_report(rows,details),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-root',type=Path)
    parser.add_argument('--output-dir',type=Path,default=REPO_ROOT/'evaluation')
    args=parser.parse_args()
    data=load_all_data(args.dataset_root)
    target=args.output_dir.resolve()
    if target==data.root or data.root in target.parents:
        parser.error('output-dir must be outside the input dataset')
    rows,details=evaluate_samples(data)
    details['input_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(data.root.glob('*.csv'))}
    write_artifacts(target,rows,details)
    stats=details['metrics_by_estimator'][DEFAULT_POLICY.amount_method]
    print(f"Samples: {len(rows)}; safe-amount exact: {stats['safe_amount_exact_matches']}/{len(rows)}; earliest-date exact: {stats['earliest_date_exact_matches']}/{len(rows)}")
    print(f"Date within 1/3/7 days (present pairs): {stats['earliest_date_within_1_day_present_pairs']}/{stats['earliest_date_within_3_days_present_pairs']}/{stats['earliest_date_within_7_days_present_pairs']}; missing/present mismatches: {stats['earliest_date_missing_present_mismatches']}")
    print(f"Default 25-request runtime: {fmt(details['performance'][DEFAULT_POLICY.amount_method]['total_seconds'])} seconds")
    print('Wrote phase4_capacity_results.csv, phase4_capacity_report.md, phase4_capacity_details.json')


if __name__=='__main__':
    main()
