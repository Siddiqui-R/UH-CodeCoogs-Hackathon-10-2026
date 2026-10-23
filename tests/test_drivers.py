import json
import unittest

from stormdata.common import ROOT, read_csv
from stormdata.drivers import clusters, quartiles, ranks, spearman


class StatsTests(unittest.TestCase):
    def test_ties_share_an_average_rank(self):
        self.assertEqual(ranks([10, 20, 20, 30]), [0, 1.5, 1.5, 3])

    def test_spearman_ignores_scale(self):
        self.assertAlmostEqual(spearman([1, 2, 3, 4], [1, 10, 100, 1000]), 1.0)
        self.assertAlmostEqual(spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)

    def test_quartiles_split_lowest_and_highest(self):
        rows = [dict(zip_code=str(i), y=i) for i in range(8)]
        low, high = quartiles(rows, 'y')
        self.assertEqual([r['y'] for r in low], [0, 1])
        self.assertEqual([r['y'] for r in high], [6, 7])
        self.assertEqual(rows[0]['downtime_quartile'], 1)
        self.assertEqual(rows[7]['downtime_quartile'], 4)

    def test_clusters_join_nearby_points_only(self):
        pts = [dict(zip_code='a', latitude=29.0, longitude=-95.0), dict(zip_code='b', latitude=29.03, longitude=-95.0),
               dict(zip_code='c', latitude=29.06, longitude=-95.0), dict(zip_code='d', latitude=30.0, longitude=-95.0)]
        groups = sorted(sorted(p['zip_code'] for p in g) for g in clusters(pts, 5.0))
        self.assertEqual(groups, [['a', 'b', 'c'], ['d']])  # chained within 5 km; d is ~110 km away


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / 'data' / 'processed'
        if not (self.p / 'downtime_recommendations.json').exists():
            self.skipTest('Run python -m stormdata.build first')

    def test_flood_claims_are_the_leading_trait(self):
        corr = read_csv(self.p / 'downtime_driver_correlations.csv')
        self.assertEqual(corr[0]['trait'], 'flood_claims_per_1k_customers')
        self.assertGreater(float(corr[0]['spearman_r']), 0.3)

    def test_recommendations_cite_real_findings(self):
        ids = {f['finding_id'] for f in read_csv(ROOT / 'data/raw/reports/report_findings.csv')}
        recs = json.loads((self.p / 'downtime_recommendations.json').read_text())['recommendations']
        self.assertGreaterEqual(len(recs), 4)
        for r in recs:
            self.assertTrue(set(r['findings'].split(';')) <= ids, r['id'])

    def test_hotspots_exclude_tiny_zips(self):
        tiny = {r['zip_code'] for r in read_csv(self.p / 'zip_downtime_drivers.csv') if r['small_denominator'] == 'True'}
        for h in read_csv(self.p / 'downtime_hotspots.csv'):
            self.assertFalse(set(h['zips'].split(';')) & tiny)


if __name__ == '__main__':
    unittest.main()
