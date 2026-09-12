"""Visible-sample audit metadata only; never imported by production forecasting.

These are manual reviews of supplied messages, not amounts/dates or overrides.
Unknown messages are always marked unresolved. No label is used as a prediction.
"""

# True means the existing cash/status/history gates already implement the stated
# exclusion. False means a future amendment remains unapplied or under-specified.
MESSAGE_REVIEWS = {
    'message_01': (False, 'Salary increase effective 2025-08-15 is not applied.'),
    'message_02': (False, 'Regular next payroll confirmed; historical blank payslip and one-off adjustment need separation.'),
    'message_03': (True, 'Unapproved quarterly bonus: excluded from recurring income; no future bonus added.'),
    'message_04': (False, 'Temporary reduced pay continues for next cycle; mean history does not apply this amendment.'),
    'message_05': (False, 'Confirmed salary delayed to 2024-09-23; scope beyond that cycle is unclear. Historical 15th projections are unamended.'),
    'message_06': (False, 'Next salary changed for unpaid leave; no amendment applied.'),
    'message_07': (True, 'Non-withdrawable pending gig payout is not recurring regular salary or confirmed credit.'),
    'message_08': (False, 'Changed confirmed base salary is not applied; speculative commissions are excluded.'),
    'message_09': (True, 'Seasonal contract ended; seasonal/temporary salary already excluded by history gate.'),
    'message_10': (False, 'Salary resumes and childcare begins; childcare amount unspecified, both amendments unapplied.'),
    'message_11': (False, 'First confirmed salary amount/date absent from structured scheduled rows; amendment unapplied.'),
    'message_12': (False, 'Next rent increases 12%; unresolved rent bill amount also requires evidence.'),
    'message_13': (True, 'Internal historical transfer pair is not replayed or projected as recurring salary/expense.'),
    'message_14': (True, 'Refund not credited: pending credit excluded.'),
    'message_15': (True, 'Unrealized portfolio valuation is non-cash and excluded.'),
    'message_16': (True, 'Uncredited prize claim: no speculative future prize cash added.'),
    'message_17': (True, 'Already-settled one-time prize is in opening balance; not replayed or projected.'),
}


def review_sample(request, messages, images, unresolved_sources):
    reviews = [{'message_id': message.message_id,
                'existing_rules_cover_fact': MESSAGE_REVIEWS.get(message.message_id, (False,''))[0],
                'reason': MESSAGE_REVIEWS.get(message.message_id, (False,'Unreviewed message'))[1]}
               for message in messages]
    blockers = []
    if any(not row['existing_rules_cover_fact'] for row in reviews):
        blockers.append('unapplied_or_ambiguous_message_amendment')
    if images:
        blockers.append('unextracted_image_or_missing_historical_amount')
    if unresolved_sources:
        blockers.append('incomplete_structured_future_amounts')
    if request.spending_changes_needed not in {'', 'none'}:
        blockers.append('labeled_spending_changes_unapplied')
    return {'message_reviews': reviews, 'timing_probe_blockers': blockers,
            'conditional_timing_support_eligible': not blockers,
            'remaining_common_assumption':'Provisional recurrence is a point forecast, not a uniquely identified conservative ledger.'}
