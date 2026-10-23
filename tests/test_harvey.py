import json
import unittest

from stormdata.common import ROOT, COUNTIES
from stormdata.harvey import LambertConformal, inside, OUTAGE_ZIP, DAMAGE_ZIP, build_supplement

TX_SOUTH_CENTRAL = ('PROJCS["x",GEOGCS["g",DATUM["d",SPHEROID["GRS_1980",6378137.0,298.257222101]],UNIT["Degree",0.0174532925199433]],'
    'PROJECTION["Lambert_Conformal_Conic"],PARAMETER["False_Easting",1968500.0],PARAMETER["False_Northing",13123333.33333333],'
    'PARAMETER["Central_Meridian",-99.0],PARAMETER["Standard_Parallel_1",28.38333333333333],'
    'PARAMETER["Standard_Parallel_2",30.28333333333334],PARAMETER["Latitude_Of_Origin",27.83333333333333],UNIT["Foot_US",0.3048006096012192]]')


class GeometryTests(unittest.TestCase):
    def test_projection_origin_maps_to_false_origin(self):
        lon, lat = LambertConformal(TX_SOUTH_CENTRAL).to_lonlat(1968500.0, 13123333.33333333)
        self.assertAlmostEqual(lon, -99.0, places=6)
        self.assertAlmostEqual(lat, 27.833333, places=5)

    def test_projection_round_trip(self):
        import math
        p = LambertConformal(TX_SOUTH_CENTRAL)
        for lon, lat in [(-95.3698, 29.7604), (-94.7977, 29.3013), (-95.6, 30.3)]:
            # Forward Lambert Conformal Conic (Snyder 15-7), then back through the inverse.
            rho = p.aF * p._t(math.radians(lat)) ** p.n
            theta = p.n * (math.radians(lon) - p.lon0)
            x = (p.fe + rho * math.sin(theta)) / p.unit
            y = (p.fn + p.rho0 - rho * math.cos(theta)) / p.unit
            back = p.to_lonlat(x, y)
            self.assertAlmostEqual(back[0], lon, places=7)
            self.assertAlmostEqual(back[1], lat, places=7)

    def test_hole_is_outside(self):
        outer = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
        hole = [(4, 4), (6, 4), (6, 6), (4, 6), (4, 4)]
        self.assertTrue(inside(2, 2, [outer, hole]))
        self.assertFalse(inside(5, 5, [outer, hole]))
        self.assertFalse(inside(11, 5, [outer]))


@unittest.skipUnless((ROOT / OUTAGE_ZIP).exists() and (ROOT / DAMAGE_ZIP).exists(), 'Harvey geodatabase zips not present')
class SupplementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        geo = json.loads((ROOT / 'greater_houston_counties.geojson').read_text())
        cls.s = build_supplement(ROOT, geo)

    def test_known_zips_land_in_expected_counties(self):
        a = {z['zip_code']: z for z in self.s['zip_assignments']}
        for zip_code, fips in {'77002': '48201', '77362': '48339', '77479': '48157', '77550': '48167', '77566': '48039'}.items():
            self.assertEqual(a[zip_code]['study_county_fips'], fips, zip_code)

    def test_map_boundaries_cover_all_zips_and_use_latitude_longitude(self):
        boundaries = self.s['zip_boundaries']
        self.assertEqual(set(boundaries), {r['zip_code'] for r in self.s['zip_assignments']})
        for zip_code, rings in boundaries.items():
            self.assertTrue(rings, zip_code)
            for ring in rings:
                self.assertGreaterEqual(len(ring), 3, zip_code)
                for lat, lon in ring:
                    self.assertTrue(28 < lat < 32 and -98 < lon < -93, zip_code)

    def test_every_source_row_kept_and_county_sums_conserved(self):
        self.assertEqual(len(self.s['zip_daily']), 1782)
        assigned = sum(r['outage_count'] for r in self.s['zip_daily'] if r['study_county_fips'])
        self.assertEqual(assigned, sum(r['outage_count_sum'] or 0 for r in self.s['county_daily']))

    def test_outages_above_customers_flagged_not_dropped(self):
        flagged = {(r['zip_code'], r['report_date']) for r in self.s['zip_daily'] if r['outages_exceed_customers']}
        self.assertEqual(flagged, {('77365', '2017-08-27'), ('77481', '2017-09-04')})

    def test_summary_covers_study_counties_with_damage(self):
        self.assertEqual({r['county_fips'] for r in self.s['summary']}, set(COUNTIES))
        harris = next(r for r in self.s['summary'] if r['county_fips'] == '48201')
        self.assertEqual((harris['zip_outage_peak_daily_count'], harris['zip_outage_peak_date']), (89319, '2017-08-28'))
        self.assertEqual(harris['fema_total_observations'], 68803)


if __name__ == '__main__':
    unittest.main()
