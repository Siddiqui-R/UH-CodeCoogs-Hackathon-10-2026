"""Restoration-time ("downtime") metrics from the outage data we hold.

Harvey: daily ZIP snapshots (time of day not stated) -> days from peak to 50% and 10% of peak.
Beryl: EAGLE-I hourly county means -> hours from peak to 50% and 10% of peak (i.e. 50% / 90% restored).
Thresholds never reached inside the data window are reported as not reached, never extrapolated.
"""
import collections
from datetime import date, datetime

from .common import COUNTIES


def recovery(series, step_name):
    """series: ordered list of (label, value) with value None for unknown. Returns peak and threshold timings."""
    known = [(i, k, v) for i, (k, v) in enumerate(series) if v is not None]
    if not known:
        return None
    pi, peak_label, peak = max(known, key=lambda t: (t[2], -t[0]))
    out = dict(peak=peak, peak_at=peak_label)
    for share, name in [(0.5, 'half'), (0.1, 'tenth')]:
        # Sustained rule: the first point after the peak from which every later known value stays at or
        # below the threshold. One-off source dropouts (e.g. a single near-zero hour) do not count.
        hit = None
        if peak > 0:
            after = [(i, k, v) for i, k, v in known if i > pi]
            for j, (i, k, v) in enumerate(after):
                if all(w <= share * peak for _, _, w in after[j:]):
                    hit = (i, k)
                    break
        out[f'{name}_reached'] = hit is not None
        out[f'{name}_at'] = hit[1] if hit else ''
        out[f'{step_name}_to_{name}'] = (hit[0] - pi) if hit else None
    out['last_value'] = known[-1][2]
    out['last_at'] = known[-1][1]
    return out


def harvey_zip(zip_daily):
    by_zip = collections.defaultdict(list)
    for r in zip_daily:
        by_zip[r['zip_code']].append(r)
    out = []
    for z, rows in sorted(by_zip.items()):
        rows.sort(key=lambda r: r['report_date'])
        # Daily rows are consecutive dates; index steps equal days. Check rather than assume.
        dates = [date.fromisoformat(r['report_date']) for r in rows]
        if any((b - a).days != 1 for a, b in zip(dates, dates[1:])):
            raise ValueError(f'Non-consecutive Harvey dates for ZIP {z}')
        rec = recovery([(r['report_date'], r['outage_count']) for r in rows], 'days')
        out.append(dict(zip_code=z, study_county_fips=rows[0]['study_county_fips'],
            peak_outages=rec['peak'], peak_date=rec['peak_at'], total_customers_on_peak_date=next(r['total_customers'] for r in rows if r['report_date'] == rec['peak_at']),
            days_peak_to_half=rec['days_to_half'], half_reached=rec['half_reached'],
            days_peak_to_tenth=rec['days_to_tenth'], tenth_reached=rec['tenth_reached'],
            customer_days_out_snapshot_sum=sum(r['outage_count'] for r in rows),
            last_date=rec['last_at'], outages_on_last_date=rec['last_value'],
            method='daily_snapshots_time_of_day_not_stated'))
    return out


def harvey_county(county_daily):
    out = []
    for fips, name in COUNTIES.items():
        rows = sorted((r for r in county_daily if r['county_fips'] == fips), key=lambda r: r['report_date'])
        rec = recovery([(r['report_date'], r['outage_count_sum']) for r in rows], 'days')
        if rec is None:
            continue
        out.append(dict(storm_event='Hurricane_Harvey_2017', county_fips=fips, county_name=name, source='harvey_zip_file_daily',
            peak_outages=rec['peak'], peak_at=rec['peak_at'], time_unit='days',
            to_half=rec['days_to_half'], half_reached=rec['half_reached'], half_at=rec['half_at'],
            to_tenth=rec['days_to_tenth'], tenth_reached=rec['tenth_reached'], tenth_at=rec['tenth_at'],
            outage_burden=sum(r['outage_count_sum'] or 0 for r in rows), outage_burden_unit='customer_days_snapshot_sum',
            data_ends=rec['last_at'], outages_at_data_end=rec['last_value']))
    return out


def beryl_county(hourly):
    out = []
    for fips, name in COUNTIES.items():
        rows = sorted((r for r in hourly if r['storm_event'] == 'Hurricane_Beryl_2024' and r['county_fips'] == fips), key=lambda r: r['time_utc'])
        times = [datetime.fromisoformat(r['time_utc'].replace('Z', '+00:00')) for r in rows]
        if any((b - a).total_seconds() != 3600 for a, b in zip(times, times[1:])):
            raise ValueError('Beryl hourly rows are not contiguous')
        rec = recovery([(r['time_local'], r['outage_customers_mean_observed']) for r in rows], 'hours')
        if rec is None:
            continue
        out.append(dict(storm_event='Hurricane_Beryl_2024', county_fips=fips, county_name=name, source='eaglei_hourly_observed_mean',
            peak_outages=round(rec['peak']), peak_at=rec['peak_at'], time_unit='hours',
            to_half=rec['hours_to_half'], half_reached=rec['half_reached'], half_at=rec['half_at'],
            to_tenth=rec['hours_to_tenth'], tenth_reached=rec['tenth_reached'], tenth_at=rec['tenth_at'],
            outage_burden=round(sum(r['outage_observed_sample_customer_hours'] or 0 for r in rows)), outage_burden_unit='observed_customer_hours_window_only',
            data_ends=rec['last_at'], outages_at_data_end=round(rec['last_value'])))
    return out
