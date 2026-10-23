import csv
import io
import random
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from stormdata.common import UTC, weather_time
from stormdata.build import assign_claim, claim_summaries, hour_outages, outage_index, haversine, track_at
from stormdata.fetch import RangeCSV, centerpoint_milestones
from stormdata.common import ROOT


class TimeAndOutageTests(unittest.TestCase):
    def test_chicago_summer_is_five_hours_behind_utc(self):
        self.assertEqual(weather_time('2024-07-08T00:00'), datetime(2024, 7, 8, 5, tzinfo=UTC))

    def test_missing_is_unknown_and_partial_is_not_complete(self):
        stamp = datetime(2024, 7, 8, 5, tzinfo=UTC)
        empty = hour_outages({}, '48201', stamp)
        self.assertIsNone(empty['outage_customers_mean_observed'])
        self.assertIsNone(empty['outage_observed_sample_customer_hours'])
        slots = {('48201', stamp): (100, 2), ('48201', stamp + timedelta(minutes=30)): (200, 3)}
        partial = hour_outages(slots, '48201', stamp)
        self.assertEqual(partial['outage_customers_mean_observed'], 150)
        self.assertEqual(partial['outage_observed_sample_customer_hours'], 75)
        self.assertIsNone(partial['outage_customers_mean_complete_hour'])

    def test_observed_zero_is_preserved(self):
        stamp = datetime(2024, 7, 8, 5, tzinfo=UTC)
        self.assertEqual(hour_outages({('48201', stamp): (0, 2)}, '48201', stamp)['outage_customers_mean_observed'], 0)

    def test_blank_source_count_is_not_an_observed_zero(self):
        r = dict(fips_code='48201', run_start_time='2024-07-08 00:00:00', customers_out='')
        self.assertEqual(outage_index([r]), {})

    def test_duplicate_and_off_grid_counts_rejected(self):
        r = dict(fips_code='48201', run_start_time='2024-07-08 00:00:00', customers_out='100')
        with self.assertRaises(ValueError):
            outage_index([r, r.copy()])
        with self.assertRaises(ValueError):
            outage_index([{**r, 'run_start_time': '2024-07-08 00:07:00'}])
        with self.assertRaises(ValueError):
            outage_index([{**r, 'customers_out': '-1'}])


class ClaimTests(unittest.TestCase):
    def claim(self, **overrides):
        return dict(countyCode='48201', floodEvent='Hurricane Beryl', yearOfLoss='2024',
            dateOfLoss='2024-07-08T00:00:00Z', netBuildingPaymentAmount='10.25',
            netContentsPaymentAmount='2.10', **overrides)

    def test_blank_event_never_inferred_from_date(self):
        row = self.claim(); row['floodEvent'] = ''
        self.assertEqual(assign_claim(row), (None, 'blank_event_label'))

    def test_wrong_year_and_outside_window_rejected(self):
        row = self.claim(); row['yearOfLoss'] = '2023'
        self.assertIsNone(assign_claim(row)[0])
        row = self.claim(); row['dateOfLoss'] = '2024-08-08T00:00:00Z'
        self.assertIsNone(assign_claim(row)[0])

    def test_identical_redacted_claims_not_silently_deduplicated(self):
        result, audit = claim_summaries([self.claim(), self.claim()])
        r = result[('48201', 'Hurricane_Beryl_2024')]
        self.assertEqual(r['nfip_recorded_claims'], 2)
        self.assertEqual(r['nfip_total_net_payment_usd'], 24.70)
        self.assertEqual([r['source_row'] for r in audit], [2, 3])

    def test_missing_payments_are_not_zero(self):
        row = self.claim(); row['netBuildingPaymentAmount'] = ''
        result, _ = claim_summaries([row])
        r = result[('48201', 'Hurricane_Beryl_2024')]
        self.assertIsNone(r['nfip_total_net_payment_usd'])
        self.assertEqual(r['nfip_payment_missing_component_claims'], 1)


class RangeExtractionTests(unittest.TestCase):
    def test_time_bounds_preserve_all_records_including_first_and_last(self):
        fields = 'fips_code,county,state,customers_out,run_start_time\n'
        lines = [f'48201,Harris,Texas,{i},2024-07-{i // 4000 + 1:02d} 00:00:00\n' for i in range(20000)]
        content = (fields + ''.join(lines)).encode()
        class FakeRange(RangeCSV):
            def block(self, start, end):
                return content[start:min(end + 1, len(content))]
        archive = FakeRange(dict(size=len(content)), lambda r: r['run_start_time'])
        result = list(archive.between('2024-07-02 00:00:00', '2024-07-04 00:00:00'))
        self.assertEqual(len(result), 8000)
        self.assertEqual(result[0]['customers_out'], '4000')
        self.assertEqual(result[-1]['customers_out'], '11999')

    def test_distance_is_geographic_not_degree_difference(self):
        self.assertAlmostEqual(haversine(30, -95, 30, -95), 0)
        self.assertAlmostEqual(haversine(0, 0, 0, 1), 111.195, places=2)


class CenterPointTests(unittest.TestCase):
    def test_dated_source_headline_required_not_just_phrase_anywhere(self):
        html = (ROOT / 'data/raw/centerpoint_beryl_updates.html').read_text(encoding='utf-8')
        self.assertEqual(len(centerpoint_milestones(html)), 8)
        # Move the date while keeping the numeric statement: extraction must fail.
        broken = html.replace('July 09, 2024', 'July 05, 2024')
        with self.assertRaises(ValueError):
            centerpoint_milestones(broken)


class TrackTests(unittest.TestCase):
    def track(self, gap_hours=3):
        stamp = datetime(2024, 7, 8, tzinfo=UTC)
        a = dict(SID='storm', _time=stamp, _row=2, LAT='30', LON='-96', USA_WIND='50', USA_SSHS='0')
        b = dict(a, _time=stamp + timedelta(hours=gap_hours), _row=3, LAT='30', LON='-93', USA_WIND='80', USA_SSHS='1')
        return [a, b]

    def test_interpolation_and_nearest_category(self):
        tracks = self.track()
        r = track_at(tracks, tracks[0]['_time'] + timedelta(hours=1), 30, -95)
        self.assertAlmostEqual(r['track_longitude'], -95)
        self.assertAlmostEqual(r['track_distance_to_weather_point_km'], 0)
        self.assertEqual(r['track_center_max_sustained_wind_kt'], 60)
        self.assertEqual(r['track_nearest_category'], 0)

    def test_no_extrapolation_or_interpolation_across_long_gap(self):
        tracks = self.track(6)
        self.assertEqual(track_at(tracks, tracks[0]['_time'] - timedelta(hours=1), 30, -95)['track_status'], 'outside_available_track')
        self.assertEqual(track_at(tracks, tracks[0]['_time'] + timedelta(hours=1), 30, -95)['track_status'], 'track_gap_over_3h')


if __name__ == '__main__':
    unittest.main()
