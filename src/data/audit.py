"""Reproducible structural measurements, not a challenge prediction run."""
from collections import Counter
from .loader import Dataset, DataValidationError
from .indexes import build_indexes


def payment_option_cadence(data: Dataset) -> dict[str, object]:
    installments = [row for row in data.payment_options if row.payment_method == 'installments']
    frequencies = {row.payment_frequency_days for row in installments}
    if None in frequencies:
        raise DataValidationError('installment payment_frequency_days is blank')
    return {
        'payment_option_count': len(data.payment_options),
        'installment_count': len(installments),
        'installment_frequencies': sorted(frequencies),
    }


def build_audit(data: Dataset) -> dict[str, object]:
    indexes = build_indexes(data)
    blank = [event for event in data.events if event.amount is None]
    report = {
        'row_counts': {
            'requests.csv': len(data.requests), 'sample_requests.csv': len(data.sample_requests),
            'financial_profiles.csv': len(data.profiles), 'financial_events.csv': len(data.events),
            'messages.csv': len(data.messages), 'images.csv': len(data.images),
            'request_payment_options.csv': len(data.payment_options),
            'exchange_rates.csv': len(data.exchange_rates), 'output.csv': len(data.output_template),
        },
        'unique_user_count': len(indexes.profile_by_user_id),
        'unique_request_count': len({r.request_id for r in data.requests}),
        'unique_request_count_including_samples': len(indexes.requests_by_request_id),
        **payment_option_cadence(data),
        'blank_event_amount_count': len(blank),
        'image_count': len(data.images),
        'image_files_present': sum(image.image_path(data.root).is_file() for image in data.images),
        'missing_image_ids': sorted(image.image_id for image in data.images if not image.image_path(data.root).is_file()),
        'blank_events_with_image_mapping': sum(e.event_id in indexes.images_by_related_event_id for e in blank),
        'linked_event_count': sum(e.linked_event_id is not None for e in data.events),
        'direction_distribution': dict(sorted(Counter(e.direction for e in data.events).items())),
        'status_distribution': dict(sorted(Counter(e.status for e in data.events).items())),
        'event_type_distribution': dict(sorted(Counter(e.event_type for e in data.events).items())),
        'protected_reduce_overlap_count': sum(bool(p.expense_categories_to_protect & p.expense_categories_user_is_willing_to_reduce) for p in data.profiles),
        'protected_stop_overlap_count': sum(bool(p.expense_categories_to_protect & p.expense_categories_user_is_willing_to_stop) for p in data.profiles),
        'overlap_count_unit': 'profiles with at least one overlapping category',
        'linked_event_count_unit': 'rows with nonblank linked_event_id',
    }
    return report
