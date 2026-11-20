import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.app_test import TMP_DIR
from core.analysis import analyse
from core.database import DEFAULT_DB, initialize
from core.impact_simulator import run_impact_simulation
from core.resolution_contract import create_contract
from core.safety_gate import evaluate_safety_gate
from simulator.incident_scenarios import MERCHANT, advance, start

with tempfile.TemporaryDirectory() as folder:
    path = Path(folder) / 'demo.sqlite'
    initialize(path)
    start(path, MERCHANT)
    while advance(path, MERCHANT):
        pass
    incident_id = MERCHANT.incident_id
    analyse(incident_id, path)
    create_contract(incident_id, path)
    evaluate_safety_gate(incident_id, path)
    run_impact_simulation(incident_id, path)
    original = sqlite3.connect
    def isolated(database, *args, **kwargs):
        return original(path if Path(database) == DEFAULT_DB else database, *args, **kwargs)
    with patch('sqlite3.connect', side_effect=isolated):
        app = AppTest.from_file('app.py', default_timeout=60).run()
        for target in ('Exception Genome', 'Review Centre', 'Operational Memory', 'Audit Trail'):
            app.sidebar.radio[0].set_value(target).run()
            assert not app.exception, str(app.exception)
        app.sidebar.radio[0].set_value('Review Centre').run()
        next(s for s in app.selectbox if s.label == 'Decision').set_value('APPROVE CONTROLLED ACTION')
        next(s for s in app.text_area if s.label == 'Rationale').set_value('Validated local diagnostic and impact projection')
        next(b for b in app.button if b.label == 'Record decision').click().run()
        assert not app.exception, str(app.exception)
        app.sidebar.radio[0].set_value('Resolution Centre').run()
        assert not app.exception, str(app.exception)
        assert any(row.label == 'Execute Controlled Remediation' for row in app.button)
    TMP_DIR.cleanup()
print('Merchant review approval and new navigation smoke test passed.')

