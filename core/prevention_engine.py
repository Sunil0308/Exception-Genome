"""Evidence-based, advisory recurrence recommendations."""
from core.phase4_store import digest

RECURRENCE_THRESHOLD = 3


def recommendations(patterns, threshold=RECURRENCE_THRESHOLD):
    result = []
    for pattern in patterns:
        if pattern['verified'] < threshold or pattern['failed']:
            continue
        case = pattern['records'][0]
        if 'CREDENTIAL_ROTATION_FAILED' not in case['genome_pattern']['change_event_type']:
            continue
        result.append(dict(prevention_id='PRE-' + digest(pattern['pattern_id'])[:16],
                           pattern_id=pattern['pattern_id'], reason='Repeated verified credential expiry pattern',
                           evidence=[r['memory_id'] for r in pattern['records']],
                           recurrence_count=pattern['verified'], trend='Recurring',
                           recommended_control='Validate an approved replacement before expiry and schedule controlled activation.',
                           expected_preventable_condition='Expired active credential reference',
                           confidence='Supported by verified synthetic occurrences', status='ADVISORY'))
    return result

