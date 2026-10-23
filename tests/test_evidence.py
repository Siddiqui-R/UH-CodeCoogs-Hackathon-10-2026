import unittest

from stormdata.common import ROOT
from stormdata.reports import consensus, compare, load, normalize
from stormdata.restoration import recovery
from stormdata.staging import weighted_access, ROAD_CIRCUITY


class RecoveryTests(unittest.TestCase):
    def test_single_dropout_is_not_restoration(self):
        series = [('t0', 100), ('t1', 1000), ('t2', 900), ('t3', 5), ('t4', 800), ('t5', 400), ('t6', 50)]
        r = recovery(series, 'hours')
        self.assertEqual((r['peak'], r['peak_at']), (1000, 't1'))
        self.assertEqual((r['hours_to_half'], r['half_at']), (4, 't5'))   # not t3, the dropout
        self.assertEqual((r['hours_to_tenth'], r['tenth_at']), (5, 't6'))

    def test_threshold_not_reached_is_not_extrapolated(self):
        r = recovery([('a', 10), ('b', 100), ('c', 80), ('d', 60)], 'days')
        self.assertFalse(r['half_reached'])
        self.assertIsNone(r['days_to_half'])

    def test_unknown_values_are_skipped(self):
        r = recovery([('a', None), ('b', 100), ('c', None), ('d', 40)], 'days')
        self.assertEqual(r['days_to_half'], 2)


class ReportTests(unittest.TestCase):
    def test_every_quote_is_on_its_page(self):
        manifest, findings = load(ROOT)  # raises if a quote is missing
        self.assertGreaterEqual(len(findings), 40)
        self.assertTrue(all(f['quote_verified'] for f in findings))

    def test_consensus_counts_distinct_reports(self):
        reports = [dict(report_id=x) for x in 'abc']
        findings = [dict(finding_id='1', report_id='a', issue_category='vegetation_trees', publisher_type='utility', storm='S1'),
                    dict(finding_id='2', report_id='a', issue_category='vegetation_trees', publisher_type='utility', storm='S1'),
                    dict(finding_id='3', report_id='b', issue_category='vegetation_trees', publisher_type='state_regulator', storm='S2')]
        c = consensus(findings, reports)[0]
        self.assertEqual((c['reports_raising'], c['reports_total']), (2, 3))
        self.assertTrue(c['raised_in_both_storms'] and c['utility_and_regulator_agree'])

    def test_unit_and_geography_mismatches_are_not_called_disagreement(self):
        a = dict(source='A', value=100, unit='customers', scope='x')
        self.assertEqual(compare('D', 's', 't', 'k', a, dict(a, unit='people'), '')['verdict'], 'unit_mismatch')
        self.assertEqual(compare('D', 's', 't', 'k', a, dict(a, scope='y'), '')['verdict'], 'different_geography')
        self.assertEqual(compare('D', 's', 't', 'k', a, dict(a, value=105), '')['verdict'], 'agree_within_10pct')
        self.assertEqual(compare('D', 's', 't', 'k', a, dict(a, value=200), '')['verdict'], 'disagree')

    def test_normalize_joins_wrapped_lines(self):
        self.assertEqual(normalize('a  \n b’s'), "a b's")


class StagingTests(unittest.TestCase):
    def test_weighted_access_and_added_site_never_hurts(self):
        demand = [dict(lat=29.0, lon=-95.0, weight=3), dict(lat=29.0, lon=-95.1, weight=1)]
        site = [dict(site_id='a', lat=29.0, lon=-95.0)]
        base = weighted_access(demand, site)
        km_per_deg = 111.195 * 0.8746  # cos(29 deg)
        self.assertAlmostEqual(base['weighted_road_km'], 0.1 * km_per_deg / 4 * ROAD_CIRCUITY, places=1)
        better = weighted_access(demand, site + [dict(site_id='b', lat=29.0, lon=-95.1)])
        self.assertEqual(better['weighted_road_km'], 0)


if __name__ == '__main__':
    unittest.main()
