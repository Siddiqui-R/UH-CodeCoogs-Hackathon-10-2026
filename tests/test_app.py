import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from app import ROOT, IntegrityCheck, create_server, describe_selection, load_summary, readiness


PASS = dict(passed=True, checked_at_utc='2026-10-23T16:00:00+00:00', detail='Test integrity result', meaning='Processing checks only')


class ReadinessTests(unittest.TestCase):
    def test_missing_harvey_outages_are_reported_as_missing(self):
        d = readiness(ROOT, 'Hurricane_Harvey_2017', '48039', 'history', PASS)
        self.assertEqual(d['selection']['outage_state'], 'missing')
        self.assertEqual(d['selection']['missing_outage_quarters'], 1152)
        self.assertEqual(d['selection']['usable_outage_percent'], 0)

    def test_complete_beryl_records_do_not_claim_full_recovery(self):
        d = readiness(ROOT, 'Hurricane_Beryl_2024', '48201', 'history', PASS)
        self.assertEqual(d['selection']['outage_state'], 'complete')
        self.assertEqual(d['selection']['missing_outage_quarters'], 0)
        self.assertIn('past the current window', d['next_data'][0]['benefit'])

    def test_forecasting_requires_independent_storms_and_archived_forecasts(self):
        d = readiness(ROOT, 'Hurricane_Beryl_2024', '48201', 'forecasting', PASS)
        self.assertIn('tested model', d['verdict'])
        self.assertIn('independent storms', d['next_data'][0]['name'])
        self.assertIn('Archived forecasts', d['next_data'][1]['name'])

    def test_preparedness_needs_population_and_facility_data(self):
        d = readiness(ROOT, 'Hurricane_Beryl_2024', '48201', 'preparedness', PASS)
        self.assertIn('Population', d['next_data'][0]['name'])
        self.assertIn('Critical facilities', d['next_data'][1]['name'])

    def test_failed_integrity_overrides_historical_readiness(self):
        d = readiness(ROOT, 'Hurricane_Beryl_2024', '48201', 'history', {**PASS, 'passed': False})
        self.assertIn('File checks failed', d['verdict'])

    def test_unknown_selection_and_goal_are_rejected(self):
        with self.assertRaises(ValueError):
            readiness(ROOT, 'made_up', '48201', 'history', PASS)
        with self.assertRaises(ValueError):
            readiness(ROOT, 'Hurricane_Beryl_2024', '48201', 'made_up', PASS)

    def test_integrity_cache_and_forced_recheck(self):
        check = IntegrityCheck(ROOT)
        result = type('Result', (), dict(returncode=0, stdout='PASS', stderr=''))()
        with patch('app.subprocess.run', return_value=result) as run:
            self.assertTrue(check.check()['passed'])
            check.check()
            self.assertEqual(run.call_count, 1)
            check.check(force=True)
            self.assertEqual(run.call_count, 2)


class LocalServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Check:
            def check(self, force=False):
                return PASS
        cls.server = create_server(0, integrity=Check())
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_root_opens_dashboard(self):
        with urllib.request.urlopen(self.base) as response:
            self.assertTrue(response.url.endswith('/dashboard/'))
            self.assertIn('Can I trust these results?', response.read().decode('utf-8'))

    def test_api_returns_selected_county(self):
        with urllib.request.urlopen(self.base + '/api/readiness?county=48039&storm=Hurricane_Harvey_2017') as response:
            self.assertEqual(json.load(response)['selection']['county_name'], 'Brazoria')

    def test_api_rejects_unknown_county(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + '/api/readiness?county=00000')
        self.assertEqual(ctx.exception.code, 400)

    def test_repository_internals_and_source_claims_are_not_served(self):
        for path in ['/.git/config', '/app.py', '/houston_fema_flood_claims_2017_present.csv', '/dashboard/../app.py']:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(self.base + path)
            self.assertEqual(ctx.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
