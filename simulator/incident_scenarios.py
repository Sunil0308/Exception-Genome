"""Scenario configuration; wrappers preserve the existing public API."""
from dataclasses import dataclass, replace

@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    incident_id: str
    title: str
    start_time: str
    source_service: str
    triggering_event: str
    recent_change: dict
    exception_templates: dict
    domain_templates: dict
    severity_rules: dict
    failed_domains: tuple
    propagation_rule: str = 'descendants'
    timing_interval: int = 8
    first_delay: int = 10
    additional_sources: tuple = ()
    sources_without_change: tuple = ()

DATAHUB = Scenario(
    'datahub-credential', 'INC-2026-001', 'DataHub Credential Failure',
    '2026-11-17T09:00:00', 'datahub', 'CREDENTIAL_EXPIRED',
    {'service_id':'datahub', 'timestamp':'2026-11-17T08:59:00',
     'type':'CREDENTIAL_ROTATION_FAILED', 'credential_state':'EXPIRED',
     'description':'DataHub credential rotation failed at 08:59'},
    {'datahub':('AUTH-401-DH','Credential rejected during service authentication'),
     'revenue':('SRC-201','Required reporting source unavailable'),
     'daily_recon':('REC-104','Expected source records not received'),
     'merchant':('REF-301','Reference data lookup unavailable'),
     'statement':('CUS-220','Customer transaction data retrieval failed'),
     'finance':('EXP-510','Finance export incomplete due to missing source dataset'),
     'card':('SET-407','Settlement enrichment dependency unavailable')},
    {'Payments':('SET','Processing blocked by missing upstream data'),
     'Reconciliation':('REC','Expected source records not received'),
     'Reporting':('SRC','Required reporting source unavailable'),
     'Customer Operations':('CUS','Customer data retrieval failed'),
     'Shared Infrastructure':('DEP','Dependent data operation unavailable')},
    {'source':'CRITICAL','downstream':'HIGH'}, ('Reporting','Reconciliation'))
INCIDENT_ID = DATAHUB.incident_id

def start(path=None, scenario=DATAHUB):
    from simulator.engine import start as run
    from core.database import DEFAULT_DB
    return run(path or DEFAULT_DB, scenario)

def advance(path=None, scenario=DATAHUB):
    from simulator.engine import advance as run
    from core.database import DEFAULT_DB
    return run(path or DEFAULT_DB, scenario)

MERCHANT = replace(
    DATAHUB, scenario_id='merchant-local-job', incident_id='INC-2026-002',
    title='Merchant Settlement Local Job Failure', source_service='merchant',
    triggering_event='LOCAL_WORKER_FAILURE', recent_change={}, propagation_rule='isolated',
    exception_templates={'merchant': ('MS-JOB-502', 'Settlement worker entered invalid runtime state')},
)
AMBIGUOUS = replace(
    DATAHUB, scenario_id='ambiguous-report', incident_id='INC-2026-004',
    title='Ambiguous Dependency Failure', source_service='revenue',
    triggering_event='UNCONFIRMED_DEPENDENCY', recent_change={}, propagation_rule='isolated',
    exception_templates={'revenue': ('SRC-490', 'Report source unavailable. Origin unconfirmed.')},
)
CONCURRENT = replace(
    DATAHUB, scenario_id='concurrent-operations', incident_id='INC-2026-003',
    title='Concurrent Operations Incident', source_service='scheduler', additional_sources=('event_bus',),
    triggering_event='COMPONENT_FAILURE',
    recent_change={'type': 'COMPONENT_FAILURE', 'timestamp': '2026-11-17T08:59:00'},
    exception_templates={'scheduler': ('DEP-510', 'Scheduler worker failed'),
                         'batch': ('SET-502', 'Scheduled processing blocked'),
                         'event_bus': ('SRC-510', 'Event stream unavailable'),
                         'notification': ('DEP-512', 'Event delivery dependency failed')},
)
MIXED = replace(
    CONCURRENT, scenario_id='mixed-operations', incident_id='INC-2026-007',
    title='Scheduler cluster and isolated Merchant failure', additional_sources=('merchant',),
    sources_without_change=('merchant',),
    exception_templates={**CONCURRENT.exception_templates, **MERCHANT.exception_templates},
)
SCENARIOS = {scenario.incident_id: scenario for scenario in (DATAHUB, MERCHANT, CONCURRENT, AMBIGUOUS, MIXED)}


def get_scenario(incident_id):
    if incident_id.startswith('INC-REC-') and incident_id[8:].isdigit():
        return replace(DATAHUB, incident_id=incident_id, title='DataHub Credential Failure recurrence')
    return SCENARIOS.get(incident_id)



