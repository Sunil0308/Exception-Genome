import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from core.database import DEFAULT_DB,snapshot
from core.recovery_engine import advance_recovery
from simulator.incident_scenarios import INCIDENT_ID, advance

def tearDownModule():
    # Streamlit's test harness creates a module-level temp directory. Close it
    # explicitly too, so ResourceWarning-as-error runs are clean at shutdown.
    from streamlit.testing.v1.app_test import TMP_DIR
    target = Path(TMP_DIR.name).resolve()
    if target.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        TMP_DIR.cleanup()

class UITests(unittest.TestCase):
    def test_demo_controls_and_analysis_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'ui.db'
            original = sqlite3.connect
            def isolated(database,*args,**kwargs):
                return original(path if Path(database)==DEFAULT_DB else database,*args,**kwargs)
            with patch('sqlite3.connect',side_effect=isolated):
                app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=60).run()
                self.assertFalse(app.exception)
                self.assertEqual(app.metric[0].value,'0')
                app.button[0].click().run()
                self.assertFalse(app.exception)
                app.button[1].click().run()
                self.assertFalse(app.session_state['running'])
                self.assertEqual(app.button[1].label,'Resume')
                app.button[1].click().run()
                self.assertTrue(app.session_state['running'])
                app.session_state['running'] = False
                while advance():
                    pass
                app.run()
                self.assertEqual(app.metric[0].value,'23')
                next(b for b in app.button if b.label=='Analyse Exception Genomes').click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.metric[3].value,'1')
                self.assertEqual(snapshot()['incidents'][0]['status'],'DIAGNOSED')
                for page in ('Exception Genome','Incident Investigation','Command Centre'):
                    app.sidebar.radio[0].set_value(page).run()
                    self.assertFalse(app.exception, str(app.exception))
                app.sidebar.radio[0].set_value('Resolution Centre').run()
                next(b for b in app.button if b.label == 'Generate Resolution Contract').click().run()
                next(b for b in app.button if b.label == 'Evaluate Safety Gate').click().run()
                next(b for b in app.button if b.label == 'Run Impact Simulation').click().run()
                self.assertFalse(app.exception, str(app.exception))
                self.assertTrue(any('23 / 23 projected recovery' in m.value for m in app.markdown))
                self.assertTrue(any('READY FOR CONTROLLED EXECUTION' in m.value for m in app.markdown))
                self.assertFalse(any(b.label == 'Execute' for b in app.button))
                next(r for r in app.radio if r.label == 'Remediation candidate').set_value(
                    'Aggressive shared authentication restart').run()
                next(b for b in app.button if b.label == 'Generate Resolution Contract').click().run()
                next(b for b in app.button if b.label == 'Evaluate Safety Gate').click().run()
                self.assertTrue(next(b for b in app.button if b.label == 'Run Impact Simulation').disabled)
                next(b for b in app.button if b.label == 'Run isolated unsafe demonstration').click().run()
                self.assertFalse(app.exception, str(app.exception))
                self.assertEqual(next(m for m in app.metric if m.label == 'New failures').value, '1')
                self.assertEqual(len([e for e in snapshot()['exceptions'] if e['status'] == 'ACTIVE']), 23)
                app.sidebar.radio[0].set_value('Command Centre').run()
                next(b for b in app.button if b.label=='Reset synthetic demo').click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.metric[0].value,'0')
                self.assertEqual(app.metric[3].value,'0')

                def click(label):
                    next(b for b in app.button if b.label == label).click().run()
                    self.assertFalse(app.exception, str(app.exception))

                for failure in (False, True):
                    click('Simulate Incident')
                    app.session_state['running'] = False
                    while advance():
                        pass
                    app.run()
                    click('Analyse Exception Genomes')
                    app.sidebar.radio[0].set_value('Resolution Centre').run()
                    self.assertFalse(any(b.label == 'Execute Controlled Remediation' for b in app.button))
                    next(r for r in app.radio if r.label == 'Remediation candidate').set_value(
                        'Approved reference activation').run()
                    click('Generate Resolution Contract')
                    click('Evaluate Safety Gate')
                    click('Run Impact Simulation')
                    next(r for r in app.radio if r.label == 'Execution mode').set_value(
                        'SYNTHETIC_VERIFICATION_FAILURE' if failure else 'NORMAL').run()
                    click('Execute Controlled Remediation')
                    for _ in range(24):
                        if snapshot()['incidents'][0]['status'] != 'RECOVERING':
                            break
                        advance_recovery(INCIDENT_ID)
                    app.run()
                    self.assertEqual(snapshot()['incidents'][0]['status'], 'AWAITING_VERIFICATION')
                    click('Run Independent Verification')
                    if failure:
                        self.assertTrue(any('VERIFICATION FAILED' in item.value for item in app.error))
                        self.assertEqual(snapshot()['incidents'][0]['status'], 'HUMAN_REVIEW_REQUIRED')
                    else:
                        self.assertTrue(any('RESOLUTION VERIFIED' in item.value for item in app.success))
                        self.assertEqual(snapshot()['incidents'][0]['status'], 'RESOLVED')
                    app.sidebar.radio[0].set_value('Command Centre').run()
                    self.assertEqual(app.metric[0].value, '23' if failure else '0')
                    click('Reset synthetic demo')
