import unittest
from datetime import datetime

from stormdata.common import ROOT
from stormdata.filegdb import Reader, GeoDatabase

OUTAGES = ROOT / 'Hurricane_Harvey_Power_Outages_by_Zip_Code.zip'
DAMAGES = ROOT / 'Hurricane_Harvey_FEMA_Modeled_Damages.zip'
FLOW = ROOT / 'Hurricane_Harvey_Flow.zip'


class VarUIntTests(unittest.TestCase):
    def test_multi_byte_value(self):
        self.assertEqual(Reader(bytes([0xAC, 0x02])).varuint(), 300)


@unittest.skipUnless(OUTAGES.exists() and DAMAGES.exists() and FLOW.exists(), 'Harvey geodatabase zips not present')
class HarveyGeodatabaseTests(unittest.TestCase):
    def test_outages_are_daily_by_zip(self):
        db = GeoDatabase(OUTAGES)
        rows = db.rows('Hurricane_Harvey_Power_Outages_by_Zip_Code')
        self.assertEqual(len(rows), 1782)
        self.assertEqual(len({r['Zip_Code'] for r in rows}), 198)
        first = rows[0]
        self.assertEqual((first['Zip_Code'], first['Event_Date'], first['Outage_Count'], first['Total_Customers']),
                         ('77362', datetime(2017, 8, 27), 51.0, 2228.0))
        for r in rows:  # stored date must agree with its text twin
            d = r['Event_Date']
            self.assertEqual(f'{d.month}/{d.day}/{d.year}', r['Event_Date_String'])

    def test_damage_categories_sum_to_total(self):
        db = GeoDatabase(DAMAGES)
        rows = db.rows(db.user_tables()[0])
        self.assertEqual(sorted(r['GEOID'] for r in rows)[:2], ['48039', '48071'])
        for r in rows:
            parts = sum(v for k, v in r.items() if k.startswith(('Affected_', 'Major_')))
            self.assertEqual(parts, r['Total_Observations'])

    def test_flow_tables(self):
        db = GeoDatabase(FLOW)
        self.assertEqual({n: len(db.rows(n)) for n in db.user_tables()},
                         {'Hurricane_Harvey_USGS_Flood_Stage': 50, 'Hurricane_Harvey_USGS_Days_Above_Flood_Stage': 24})


if __name__ == '__main__':
    unittest.main()
