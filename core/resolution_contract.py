"""Freeze diagnosis evidence and translate it through a deterministic action policy."""
import json
from dataclasses import asdict, dataclass, replace

from core.action_registry import ACTION_REGISTRY, ACTIVATE, RESTART, ROTATE
from core.analysis import read_analysis
from core.database import DEFAULT_DB, connect
from core.exception_genome import decode
from core.phase4_store import audit, canonical, digest, identifier, now


@dataclass(frozen=True)
class ResolutionContract:
    contract_id: str
    incident_id: str
    cluster_id: str
    analysis_id: str
    created_at: str
    root_cause: str
    root_cause_service: str
    root_cause_evidence_score: float
    correlation_score: float
    proposed_action: str
    action_type: str
    target_service: str
    action_parameters: dict
    autonomy_class: str
    risk_class: str
    evidence_snapshot: dict
    required_preconditions: tuple
    expected_postconditions: tuple
    rollback_plan: dict
    authority_scope: dict
    maximum_blast_radius: int
    contract_version: int
    contract_hash: str
    status: str


PRECONDITIONS = (
    'Current diagnosed and unresolved incident', 'Failed root service and expired authentication context',
    'Timely failed change with supporting evidence', 'Unique strongest candidate above evidence thresholds',
    'No material contradictions', 'Approved valid replacement reference and confirmed expired active reference',
    'No equivalent remediation recorded', 'Allowlisted action limited to one declared configuration target',
)
POSTCONDITIONS = (
    'Projected valid DataHub authentication', 'DataHub eligible for recovery',
    'Downstream connectivity can resume', 'Downstream services become eligible for recovery',
    'Active exception count is expected to decrease after controlled execution',
)


def contract_hash(contract):
    fields = asdict(contract)
    for key in ('created_at', 'contract_id', 'contract_hash', 'contract_version', 'status'):
        del fields[key]
    fields['evidence_snapshot'].pop('snapshot_at', None)
    return digest(fields)


def read_context(db, incident_id):
    analysis = read_analysis(db, incident_id)
    incident = db.execute('SELECT id,title,status,started_at,simulation_step FROM incidents WHERE id=?', (incident_id,)).fetchone()
    return {
        'incident': dict(incident) if incident else {},
        'analysis': analysis,
        'services': [dict(row) for row in db.execute('SELECT * FROM services ORDER BY id')],
        'exceptions': [dict(row) for row in db.execute('SELECT * FROM exceptions ORDER BY id')],
        'references': [dict(row) for row in db.execute('SELECT * FROM approved_resource_references ORDER BY reference_id')],
    }


def evidence_for(context, cluster_id):
    analysis = context['analysis']
    cluster = next((row for row in analysis['correlation_clusters'] if row['id'] == cluster_id), {})
    root = next((row for row in analysis['root_cause_analyses'] if row.get('cluster_id') == cluster_id), {})
    root_id = root.get('root_cause_service_id')
    services = {row['id']: row for row in context['services']}
    incident_id = context['incident'].get('id')
    rows = [row for row in context['exceptions'] if row['incident_id'] == incident_id]
    if len(analysis['correlation_clusters']) > 1:
        rows = [row for row in rows if row['id'] in cluster.get('members', [])]
    source = next((row for row in rows if row['service_id'] == root_id), {})
    change = decode(source.get('recent_change_event'), {})
    return dict(diagnosis=root, correlation_score=cluster.get('score'),
                genome_signatures={g['exception_id']: g['genome_signature']
                                   for g in analysis['exception_genomes'] if g['exception_id'] in cluster.get('members', [])},
                root_service_state=services.get(root_id, {}),
                source_exception=source, incident_exceptions=rows,
                change_event=change if isinstance(change, dict) else {},
                affected_service_count=len({row['service_id'] for row in rows if row['id'] in cluster.get('members', [])}),
                conflicting_evidence=root.get('conflicting_evidence'),
                alternative_hypotheses=root.get('alternative_hypotheses'))


def current_contract(db, incident_id, cluster_id=None):
    sql = 'SELECT payload,status FROM resolution_contracts WHERE incident_id=?'
    args = (incident_id,)
    if cluster_id is not None:
        sql += ' AND cluster_id=?'
        args += (cluster_id,)
    row = db.execute(sql + ' ORDER BY version DESC LIMIT 1', args).fetchone()
    if row is None:
        return None
    fields = json.loads(row['payload'])
    fields['status'] = row['status']
    for key in ('required_preconditions', 'expected_postconditions'):
        fields[key] = tuple(fields[key])
    return ResolutionContract(**fields)


def create_contract(incident_id, path=DEFAULT_DB, *, unsafe_demo=False, cluster_id=None):
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        context = read_context(db, incident_id)
        roots = context['analysis']['root_cause_analyses']
        if cluster_id is not None:
            roots = [r for r in roots if r['cluster_id'] == cluster_id]
        if context['incident'].get('status') != 'DIAGNOSED' or len(roots) != 1 or not roots[0].get('analysis_id'):
            raise ValueError('A current incident diagnosis with one identified root is required.')
        root = roots[0]
        evidence = evidence_for(context, root['cluster_id'])
        evidence['snapshot_at'] = now()
        target = root['root_cause_service_id']
        action_type, proposal, parameters, rollback = 'ESCALATE', 'Escalate diagnosis for review', {}, {}
        if unsafe_demo:
            action_type, target, proposal = RESTART, 'auth', 'Aggressive shared authentication restart'
        elif root.get('diagnosis_outcome') == 'NO_CONFIDENT_ROOT_CAUSE':
            pass
        elif root.get('recommended_action_type') == ROTATE:
            action_type, proposal = ROTATE, 'Credential creation or rotation requested by analysis'
        elif (target == 'merchant' and evidence['source_exception'].get('error_code') == 'MS-JOB-502'
              and evidence['affected_service_count'] == 1 and not evidence['conflicting_evidence']):
            action_type, proposal = RESTART, 'Restart the isolated Merchant Settlement worker'
        elif target in ('scheduler', 'event_bus') and evidence['change_event'].get('type') == 'COMPONENT_FAILURE':
            action_type, proposal = RESTART, f"Restart the {root['root_cause_service']} component"
        elif (target == 'datahub' and evidence['source_exception'].get('authentication_context') == 'CREDENTIAL_EXPIRED'
              and evidence['change_event'].get('type') == 'CREDENTIAL_ROTATION_FAILED'):
            action_type, proposal = ACTIVATE, 'Activate approved credential reference DH-v18 for DataHub API'
            parameters = {'credential_version': 'DH-v18'}
            rollback = {'action': 'RESTORE_PREVIOUS_REFERENCE', 'credential_version': 'DH-v17',
                        'target_service': target, 'escalate_on_unexpected_behavior': True}
        action = ACTION_REGISTRY[action_type]
        previous = current_contract(db, incident_id, root['cluster_id'])
        max_version = db.execute('SELECT COALESCE(MAX(version),0) FROM resolution_contracts WHERE incident_id=?',
                                 (incident_id,)).fetchone()[0]
        contract = ResolutionContract(
            identifier('RC', incident_id), incident_id, root['cluster_id'], root['analysis_id'], now(),
            root['root_cause'], root['root_cause_service_id'], round(root['confidence'] * 100, 6),
            evidence['correlation_score'], proposal, action_type, target, parameters,
            action.autonomy_class, action.default_risk, evidence, PRECONDITIONS,
            POSTCONDITIONS if action_type == ACTIVATE else (), rollback,
            {'target_type': 'SERVICE', 'targets': [target], 'surface': 'SYNTHETIC_SERVICE_CONFIGURATION'}
            if action.permitted_target_types else {'targets': []},
            action.maximum_allowed_scope, max_version + 1, '', 'CURRENT',
        )
        contract = replace(contract, contract_hash=contract_hash(contract))
        if previous and previous.status == 'CURRENT' and previous.contract_hash == contract.contract_hash and contract_hash(previous) == contract.contract_hash:
            return previous
        if previous:
            db.execute("UPDATE resolution_contracts SET status='SUPERSEDED' WHERE id=?", (previous.contract_id,))
            for table in ('safety_evaluations', 'impact_simulations', 'execution_readiness'):
                db.execute(f"UPDATE {table} SET status='STALE' WHERE contract_id=?", (previous.contract_id,))
        db.execute('INSERT INTO resolution_contracts VALUES (?,?,?,?,?,?,?)',
                   (contract.contract_id, incident_id, contract.cluster_id, contract.contract_version,
                    contract.contract_hash, contract.status, canonical(asdict(contract))))
        for event in ('RESOLUTION_CONTRACT_CREATED', 'CONTRACT_VERSION_GENERATED'):
            audit(db, contract, event, {'version': contract.contract_version, 'hash': contract.contract_hash})
        return contract









