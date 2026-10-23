"""Build joined CSVs, an audit report, and a dependency-free dashboard payload."""
import argparse
import collections
import json
import math
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from .common import (ROOT, COUNTIES, STORMS, UTC, LOCAL, digest, number, read_csv,
                     utc_text, weather_time, write_csv, write_json)
from .harvey import DAMAGE_ZIP, OUTAGE_ZIP, build_supplement
from . import drivers, reports as report_evidence, restoration, staging

WEATHER = {
    'temperature_2m': 'temperature_c', 'precipitation': 'precipitation_in',
    'rain': 'rain_in', 'surface_pressure': 'surface_pressure_hpa',
    'wind_speed_10m': 'wind_speed_10m_mph', 'wind_speed_100m': 'wind_speed_100m_mph',
    'wind_direction_10m': 'wind_direction_deg', 'wind_gusts_10m': 'wind_gusts_10m_mph',
    'soil_moisture_0_to_7cm': 'soil_moisture_m3_m3',
}
SOURCE_URLS = {
    'houston_major_storms_hourly_weather.csv': 'https://open-meteo.com/en/docs/historical-weather-api',
    'tx_gulf_hurricane_tracks_1980_present.csv': 'https://www.ncei.noaa.gov/products/international-best-track-archive',
    'houston_fema_flood_claims_2017_present.csv': 'https://www.fema.gov/openfema-data-page/fima-nfip-redacted-claims-v3',
    'greater_houston_counties.geojson': 'https://www.census.gov/geographies/mapping-files/time-series/geo/carto-boundary-file.html',
}
# Organizer-supplied ArcGIS geodatabases; the brief names no upstream publisher or URL.
HARVEY_SOURCES = [OUTAGE_ZIP, DAMAGE_ZIP]
HARVEY_OUTPUTS = dict(zip_assignments='harvey_zip_county_assignments.csv', zip_daily='harvey_zip_outages_daily.csv',
    county_daily='harvey_county_outages_daily.csv', damages='harvey_fema_damage_assessments.csv',
    summary='harvey_county_supplement.csv')


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = p2 - p1, math.radians(lon2 - lon1)
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(
        math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2)))


def track_at(tracks, when, lat, lon):
    before = [r for r in tracks if r['_time'] <= when]
    after = [r for r in tracks if r['_time'] >= when]
    empty = dict(track_sid=tracks[0]['SID'], track_status='outside_available_track',
        track_latitude=None, track_longitude=None, track_distance_to_weather_point_km=None,
        track_center_max_sustained_wind_kt=None, track_nearest_category=None,
        track_source_row_before=None, track_source_row_after=None)
    if not before or not after:
        return empty
    a, b = before[-1], after[0]
    seconds = (b['_time'] - a['_time']).total_seconds()
    if seconds > 3 * 3600:
        empty['track_status'] = 'track_gap_over_3h'
        return empty
    weight = 0 if seconds == 0 else (when - a['_time']).total_seconds() / seconds
    def interpolate(key):
        x, y = number(a[key]), number(b[key])
        return None if x is None or y is None else x + (y - x) * weight
    tlat, tlon = interpolate('LAT'), interpolate('LON')
    nearest = a if weight <= 0.5 else b
    return dict(track_sid=a['SID'], track_status='observed' if seconds == 0 else 'center_interpolated_le_3h',
        track_latitude=tlat, track_longitude=tlon,
        track_distance_to_weather_point_km=round(haversine(lat, lon, tlat, tlon), 3),
        track_center_max_sustained_wind_kt=interpolate('USA_WIND'),
        track_nearest_category=number(nearest['USA_SSHS']),
        track_source_row_before=a['_row'], track_source_row_after=b['_row'])


def outage_index(rows):
    slots = {}
    seen = set()
    for index, r in enumerate(rows, 2):
        fips = r['fips_code'].zfill(5)
        stamp = datetime.fromisoformat(r['run_start_time'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)  # Documented EAGLE-I UTC convention.
        stamp = stamp.astimezone(UTC)
        if stamp.minute % 15 or stamp.second or stamp.microsecond:
            raise ValueError(f'Off-grid outage timestamp on row {index}')
        count = number(r.get('customers_out', r.get('sum')))
        if count is not None and (count < 0 or not count.is_integer()):
            raise ValueError(f'Invalid outage count on row {index}')
        key = (fips, stamp)
        if key in seen:
            raise ValueError(f'Duplicate county-quarter-hour: {key}')
        seen.add(key)
        if count is None:
            continue  # Blank source counts stay unknown, with a separate exclusion audit.
        slots[key] = (int(count), index)
    return slots


def hour_outages(slots, fips, when):
    values = [slots.get((fips, when + timedelta(minutes=15 * n))) for n in range(4)]
    observed = [v for v in values if v is not None]
    counts = [v[0] for v in observed]
    return dict(outage_observed_quarters=len(counts), outage_expected_quarters=4,
        outage_record_presence_fraction=len(counts) / 4,
        outage_customers_mean_observed=sum(counts) / len(counts) if counts else None,
        outage_customers_mean_complete_hour=sum(counts) / 4 if len(counts) == 4 else None,
        outage_customers_peak_observed=max(counts) if counts else None,
        outage_observed_sample_customer_hours=sum(counts) / 4 if counts else None,
        outage_status='complete_source_hour' if len(counts) == 4 else 'partial_source_hour' if counts else 'no_source_records',
        outage_source_rows=';'.join(str(v[1]) for v in observed),
        outage_geography='county_all_reporting_utilities')


def assign_claim(row):
    if row['countyCode'] not in COUNTIES:
        return None, 'outside_selected_counties'
    for event, storm in STORMS.items():
        if row['floodEvent'] != storm['claim_label']:
            continue
        if str(storm['year']) != row['yearOfLoss']:
            return None, 'named_event_year_mismatch'
        if not storm['claim_start'] <= row['dateOfLoss'][:10] <= storm['claim_end']:
            return None, 'named_event_date_outside_documented_window'
        return event, 'exact_label_year_and_date_window'
    return None, 'blank_event_label' if not row['floodEvent'].strip() else 'other_named_event'


def claim_summaries(rows):
    groups = collections.defaultdict(list)
    audit = []
    for source_row, row in enumerate(rows, 2):
        event, reason = assign_claim(row)
        audit.append(dict(source_row=source_row, county_fips=row['countyCode'],
            date_of_loss=row['dateOfLoss'][:10], source_event_label=row['floodEvent'],
            assigned_storm_event=event or '', assignment_reason=reason))
        if event:
            groups[(row['countyCode'], event)].append(row)
    result = {}
    for fips in COUNTIES:
        for event in STORMS:
            group = groups[(fips, event)]
            payment = {}
            for column, label in [('netBuildingPaymentAmount', 'building'), ('netContentsPaymentAmount', 'contents')]:
                observed = [Decimal(r[column]) for r in group if r[column].strip()]
                payment[f'nfip_{label}_payment_usd'] = float(sum(observed, Decimal(0))) if observed or not group else None
                payment[f'nfip_{label}_payment_observed_claims'] = len(observed)
            amounts = [payment[f'nfip_{kind}_payment_usd'] for kind in ['building', 'contents']]
            payment['nfip_total_net_payment_usd'] = round(sum(amounts), 2) if all(x is not None for x in amounts) else None
            result[(fips, event)] = dict(nfip_recorded_claims=len(group), **payment,
                nfip_payment_missing_component_claims=sum(not r['netBuildingPaymentAmount'].strip() or not r['netContentsPaymentAmount'].strip() for r in group),
                nfip_loss_date_first=min((r['dateOfLoss'][:10] for r in group), default=''),
                nfip_loss_date_last=max((r['dateOfLoss'][:10] for r in group), default=''),
                nfip_claim_window_start=STORMS[event]['claim_start'], nfip_claim_window_end=STORMS[event]['claim_end'])
    return result, audit


def pearson(pairs):
    if len(pairs) < 3:
        return None
    xs, ys = zip(*pairs)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    numerator = sum((x - mx) * (y - my) for x, y in pairs)
    denom = math.sqrt(sum((x - mx)**2 for x in xs) * sum((y - my)**2 for y in ys))
    return round(numerator / denom, 4) if denom else None


def build(root=ROOT, output=None):
    root = Path(root)
    output = Path(output) if output else root / 'data' / 'processed'
    raw = root / 'data' / 'raw'
    weather = read_csv(root / 'houston_major_storms_hourly_weather.csv')
    tracks = collections.defaultdict(list)
    for index, r in enumerate(read_csv(root / 'tx_gulf_hurricane_tracks_1980_present.csv'), 2):
        r['_time'] = datetime.fromisoformat(r['ISO_TIME']).replace(tzinfo=UTC)
        r['_row'] = index
        tracks[r['SID']].append(r)
    for records in tracks.values():
        records.sort(key=lambda r: r['_time'])
    outage_file = raw / 'houston_power_outages_15min_eaglei.csv'
    if not outage_file.exists():
        raise FileNotFoundError('Run python -m stormdata.fetch first; outage inputs are required, never fabricated.')
    source_outages = read_csv(outage_file)
    slots = outage_index(source_outages)
    excluded_outages = [dict(source_row=i, county_fips=r['fips_code'], time_utc=r['run_start_time'], reason='blank_source_outage_count')
                       for i, r in enumerate(source_outages, 2) if number(r['customers_out']) is None]
    hourly, keys = [], set()
    fips_by_name = {name: fips for fips, name in COUNTIES.items()}
    for index, r in enumerate(weather, 2):
        event = r['storm_event']
        if event not in STORMS:
            raise ValueError(f'Unknown storm: {event}')
        fips = fips_by_name[r['location'].split(' (')[0]]
        when = weather_time(r['time'])
        key = (fips, event, when)
        if key in keys:
            raise ValueError(f'Duplicate county-storm-hour: {key}')
        keys.add(key)
        lat, lon = float(r['latitude']), float(r['longitude'])
        hourly.append(dict(county_fips=fips, county_name=COUNTIES[fips], storm_event=event,
            time_utc=utc_text(when), time_local=when.astimezone(LOCAL).isoformat(),
            weather_point_latitude=lat, weather_point_longitude=lon, weather_source_row=index,
            **{dest: number(r[source]) for source, dest in WEATHER.items()},
            **track_at(tracks[STORMS[event]['sid']], when, lat, lon), **hour_outages(slots, fips, when)))
    hourly.sort(key=lambda r: (r['storm_event'], r['county_fips'], r['time_utc']))
    county_geo = json.loads((root / 'greater_houston_counties.geojson').read_text())
    harvey = build_supplement(root, county_geo)
    claim_rows = read_csv(root / 'houston_fema_flood_claims_2017_present.csv')
    claims, audit = claim_summaries(claim_rows)
    groups = collections.defaultdict(list)
    for r in hourly:
        groups[(r['county_fips'], r['storm_event'])].append(r)
    summary = []
    for (fips, event), rows in sorted(groups.items()):
        observed = sum(r['outage_observed_quarters'] for r in rows)
        def available(col):
            return [r[col] for r in rows if r[col] is not None]
        def maximum(col):
            values = available(col)
            return max(values) if values else None
        distances = available('track_distance_to_weather_point_km')
        rain = available('precipitation_in')
        summary.append(dict(county_fips=fips, county_name=COUNTIES[fips], storm_event=event,
            window_start_utc=rows[0]['time_utc'], window_end_utc_exclusive=utc_text(datetime.fromisoformat(rows[-1]['time_utc'].replace('Z','+00:00')) + timedelta(hours=1)),
            weather_hours=len(rows), precipitation_observed_hours=len(rain),
            total_precipitation_in=round(sum(rain), 4) if len(rain) == len(rows) else None,
            peak_wind_gust_mph=maximum('wind_gusts_10m_mph'),
            min_track_distance_to_weather_point_km=min(distances) if distances else None,
            track_covered_hours=len(distances), outage_observed_quarters=observed,
            outage_expected_quarters=4 * len(rows), outage_record_presence_fraction=round(observed / (4 * len(rows)), 6),
            outage_complete_hours=sum(r['outage_observed_quarters'] == 4 for r in rows),
            outage_peak_customers_observed=maximum('outage_customers_peak_observed'),
            outage_observed_sample_customer_hours=round(sum(available('outage_observed_sample_customer_hours')), 2) if observed else None,
            recovery_duration_status='not_estimated_weather_window_may_truncate_recovery', **claims[(fips, event)]))
    # Fail instead of producing silent join multiplication or inflated payment totals.
    if len(summary) != len(COUNTIES) * len(STORMS) or len(summary) != 20:
        raise ValueError('Expected 20 county-storm combinations')
    if len(hourly) != len(weather):
        raise ValueError('Hourly join multiplied weather rows')
    if sum(r['nfip_recorded_claims'] for r in summary) != sum(bool(r['assigned_storm_event']) for r in audit):
        raise ValueError('Claim join count mismatch')
    for rows in groups.values():
        times = sorted(datetime.fromisoformat(r['time_utc'].replace('Z','+00:00')) for r in rows)
        if any(b - a != timedelta(hours=1) for a, b in zip(times, times[1:])):
            raise ValueError('Gap in supplied hourly weather')
    manifest_path = raw / 'retrieval_manifest.json'
    split_zips = sum(z['split_across_counties'] for z in harvey['zip_assignments'])
    harris_eaglei = next(r['outage_peak_customers_observed'] for r in summary
                         if r['county_fips'] == '48201' and r['storm_event'] == 'Hurricane_Harvey_2017')
    harris_zip = next(r['zip_outage_peak_daily_count'] for r in harvey['summary'] if r['county_fips'] == '48201')
    retrieval = json.loads(manifest_path.read_text(encoding='utf-8'))
    warnings = [
        'Only four independent storms and 20 county-storm combinations; hourly rows are not independent storms.',
        'County outage totals cover reporting utilities, not CenterPoint alone; no county allocation of CenterPoint milestones.',
        'Absent EAGLE-I records are unknown, not zeros. Record presence is not verified utility/customer coverage.',
        'One source outage count is blank and excluded from usable-record presence; see excluded_outage_records.csv.',
        'The official 2024 archive contains misplaced county rows; acquisition scans that entire annual source.',
        'Outage means use observed snapshots; full-hour means require all four quarter-hours. Sample customer-hours omit unknown intervals.',
        'Weather is ERA5 reanalysis at one sampling point per county; not a countywide measurement or a pre-storm forecast.',
        'Track-center wind intensity is not local wind. Tracks are clipped to the supplied Gulf bounding box; distances use available hours only.',
        'Observation windows match supplied weather and can truncate outage recovery. No household restoration durations are inferred.',
        'NFIP payments cover insured claims only, in nominal dollars. Coverage uptake, development, inflation and exposure confound county comparisons.',
        'Claims use exact named-event labels, year and explicit loss-date windows. Blank labels are not inferred; claim windows differ from weather windows.',
        'Starter files have no original download manifest. Their upstream sources/units are attributed by the challenge brief and have not been independently re-downloaded.',
        'CenterPoint figures preserve rounding/bounds and release times; these are company reports, not reconciled meter-level measurements.',
        f'Harvey ZIP outages are one snapshot per day (time of day not stated) for {len(harvey["zip_assignments"])} ZIP codes, from an organizer-supplied file with no named publisher. They are kept separate from EAGLE-I and never fill its hourly gaps.',
        f'ZIP codes are assigned whole to the county holding most of their sampled area, using simplified county outlines; {split_zips} ZIPs straddle a county line. County ZIP totals cover reporting ZIPs only.',
        f'EAGLE-I and the ZIP file disagree for Harvey and neither covers every utility: Harris peaks at {harris_eaglei:,} in EAGLE-I vs {harris_zip:,} in one ZIP-file daily snapshot, while Montgomery is higher in EAGLE-I. Treat both as partial counts.',
        'Total customers per ZIP change from day to day in the ZIP file (Harris reporting ZIPs fall from about 1.85M to 0.92M by Sep 4), so daily outage percentages use shifting denominators.',
        'FEMA modeled damage counts are housing-unit assessments by floodplain zone, not insured claims or dollars; they cover Harvey only and eight counties.',
    ]
    report = dict(status='passed_with_documented_limitations', county_storm_rows=len(summary), hourly_rows=len(hourly),
        independent_storms=len(STORMS), outage_source_rows=len(source_outages),
        usable_outage_source_rows=len(slots), blank_outage_count_rows=len(excluded_outages),
        claim_assignment_counts=dict(collections.Counter(r['assignment_reason'] for r in audit)),
        assigned_claims=sum(r['nfip_recorded_claims'] for r in summary),
        missing_outage_quarters=sum(r['outage_expected_quarters'] - r['outage_observed_quarters'] for r in summary),
        harvey_zip_outage_rows=len(harvey['zip_daily']), harvey_zips=len(harvey['zip_assignments']),
        harvey_zips_in_study_counties=sum(bool(z['study_county_fips']) for z in harvey['zip_assignments']),
        harvey_split_zips=split_zips,
        harvey_fema_damage_counties=len(harvey['damages']),
        checks=['unique county-storm-hour', 'unique county-quarter-hour', 'UTC 15-minute grid',
                'nonnegative integer outage counts', 'contiguous weather hours', '20 county-storm rows',
                'claim assignment count conservation', 'no claim columns in hourly table',
                'unique Harvey ZIP-day outages', 'Harvey ZIP dates match their text copies',
                'FEMA damage categories sum to totals'], warnings=warnings)
    associations = []
    for event in [None, *STORMS]:
        subset = [r for r in summary if event is None or r['storm_event'] == event]
        for x, y in [('peak_wind_gust_mph', 'outage_peak_customers_observed'), ('total_precipitation_in', 'nfip_total_net_payment_usd')]:
            pairs = [(r[x], r[y]) for r in subset if r[x] is not None and r[y] is not None]
            associations.append(dict(storm_event=event or 'all_four_storms', x=x, y=y,
                n_county_storm_pairs=len(pairs), pearson_r=pearson(pairs),
                interpretation='unadjusted_descriptive_only_no_p_values_no_causal_claims'))
    sources = []
    for name, url in SOURCE_URLS.items():
        sources.append(dict(file=name, sha256=digest(root / name), source_url=url,
            provenance_status='organizer_supplied_upstream_attribution_from_brief', original_retrieval_date=None))
    for name in HARVEY_SOURCES:
        sources.append(dict(file=name, sha256=digest(root / name), source_url=None,
            provenance_status='organizer_supplied_no_upstream_attribution', original_retrieval_date=None))
    for official in json.loads((raw / 'reports' / 'reports.json').read_text(encoding='utf-8'))['reports']:
        for rel in (f"reports/{official['file']}", f"reports/text/{official['file'][:-4]}.txt"):
            sources.append(dict(file=f'data/raw/{rel}', sha256=digest(raw / rel), source_url=official['source_url'],
                provenance_status='official_report_downloaded' if rel.endswith('.pdf') else 'text_extracted_from_official_report',
                retrieved_at_utc='2026-10-23T16:30:00Z'))
    for rel in ('reports/reports.json', 'reports/report_findings.csv', 'staging/staging_sites.csv',
                'staging/hifld_substations_study_counties.json', 'staging/hifld_substations_source.json'):
        sources.append(dict(file=f'data/raw/{rel}', sha256=digest(raw / rel), source_url=None,
            provenance_status='hand_curated_from_cited_sources', original_retrieval_date=None))
    for path in sorted(raw.iterdir()):
        if path.is_file() and path.suffix in ('.csv', '.json', '.html'):
            sources.append(dict(file=str(path.relative_to(root)).replace('\\','/'), sha256=digest(path),
                source_url=CNP_SOURCE if path.name.startswith('centerpoint') else retrieval['archive_metadata_url'],
                provenance_status='retrieved_official_source_or_documented_extraction', retrieved_at_utc=retrieval['retrieved_at_utc']))
    write_csv(output / 'county_storm_hour.csv', hourly)
    write_csv(output / 'county_storm.csv', summary)
    write_csv(output / 'claim_assignments.csv', audit)
    write_csv(output / 'excluded_outage_records.csv', excluded_outages, ['source_row', 'county_fips', 'time_utc', 'reason'])
    write_csv(output / 'descriptive_associations.csv', associations)
    write_csv(output / 'centerpoint_beryl_milestones.csv', read_csv(raw / 'centerpoint_beryl_milestones.csv'))
    for key, name in HARVEY_OUTPUTS.items():
        write_csv(output / name, harvey[key])
    # Official reports, discrepancies, restoration time and the staging what-if.
    report_manifest, findings = report_evidence.load(root)
    consensus = report_evidence.consensus(findings, report_manifest['reports'])
    centerpoint_rows = read_csv(raw / 'centerpoint_beryl_milestones.csv')
    discrepancies = report_evidence.discrepancies(findings, hourly, centerpoint_rows, harvey['county_daily'], harvey['zip_daily'], summary)
    zip_restoration = restoration.harvey_zip(harvey['zip_daily'])
    restoration_rows = restoration.harvey_county(harvey['county_daily']) + restoration.beryl_county(hourly)
    staging_summary, staging_meta, staging_candidates, staging_points = staging.what_if(
        read_csv(raw / 'staging' / 'staging_sites.csv'), harvey['zip_assignments'], zip_restoration, claim_rows)
    write_csv(output / 'report_findings.csv', findings)
    write_csv(output / 'report_issue_consensus.csv', consensus)
    write_csv(output / 'report_discrepancies.csv', discrepancies)
    write_csv(output / 'restoration_metrics.csv', restoration_rows)
    write_csv(output / 'harvey_zip_restoration.csv', zip_restoration)
    write_csv(output / 'staging_whatif_candidates.csv', staging_candidates)
    write_csv(output / 'staging_whatif_points.csv', staging_points)
    write_json(output / 'staging_whatif_summary.json', dict(meta=staging_meta, scenarios=staging_summary))
    write_csv(output / 'relief_sites.csv', read_csv(raw / 'staging' / 'staging_sites.csv'))
    hifld = json.loads((raw / 'staging' / 'hifld_substations_study_counties.json').read_text(encoding='utf-8'))
    substations = [dict(substation_id=a['ID'], name=a['NAME'].title(), city=(a['CITY'] or '').title(), county_fips=a['COUNTYFIPS'],
                        type=a['TYPE'].lower(), status=a['STATUS'].lower(), max_kv=a['MAX_VOLT'] if a['MAX_VOLT'] and a['MAX_VOLT'] > 0 else None,
                        lines=a['LINES'], latitude=round(a['LATITUDE'], 6), longitude=round(a['LONGITUDE'], 6),
                        hifld_source=a['SOURCE'], hifld_source_date=datetime.fromtimestamp(a['SOURCEDATE'] / 1000, UTC).date().isoformat() if a['SOURCEDATE'] else '')
                   for a in (f['attributes'] for f in hifld['features'])]
    write_csv(output / 'hifld_substations.csv', substations)
    driver_rows, driver_corr, hotspots, driver_summary, recs = drivers.build(
        zip_restoration, harvey['zip_assignments'], staging_points, claim_rows, staging_summary, restoration_rows)
    write_csv(output / 'zip_downtime_drivers.csv', driver_rows)
    write_csv(output / 'downtime_driver_correlations.csv', driver_corr)
    write_csv(output / 'downtime_hotspots.csv', hotspots)
    write_json(output / 'downtime_recommendations.json', dict(summary=driver_summary, recommendations=recs))
    geo = county_geo
    geo['features'] = [f for f in geo['features'] if f['properties']['id'] in COUNTIES]
    write_json(output / 'counties.geojson', geo)
    write_json(output / 'validation_report.json', report)
    write_json(output / 'source_manifest.json', dict(sources=sources, retrieval_manifest='data/raw/retrieval_manifest.json'))
    outputs = ['county_storm_hour.csv', 'county_storm.csv', 'claim_assignments.csv',
        'excluded_outage_records.csv', 'descriptive_associations.csv', 'centerpoint_beryl_milestones.csv',
        'counties.geojson', 'source_manifest.json', 'validation_report.json', *HARVEY_OUTPUTS.values(),
        'report_findings.csv', 'report_issue_consensus.csv', 'report_discrepancies.csv', 'restoration_metrics.csv',
        'harvey_zip_restoration.csv', 'staging_whatif_candidates.csv', 'staging_whatif_points.csv', 'staging_whatif_summary.json', 'relief_sites.csv', 'hifld_substations.csv',
        'zip_downtime_drivers.csv', 'downtime_driver_correlations.csv', 'downtime_hotspots.csv', 'downtime_recommendations.json']
    processing = dict(
        storm_definitions=STORMS, counties=COUNTIES, weather_columns_and_units=WEATHER,
        weather_timezone='America/Chicago', canonical_timezone='UTC', outage_expected_interval_minutes=15,
        missing_outage_policy='unknown_no_zero_imputation', track_max_interpolation_gap_hours=3,
        payment_fields=['netBuildingPaymentAmount', 'netContentsPaymentAmount'],
        claim_assignment='exact_event_label_and_year_and_inclusive_loss_date_window',
        code_sha256={f.name: digest(f) for f in sorted((ROOT / 'stormdata').glob('*.py'))},
        output_sha256={name: digest(output / name) for name in outputs})
    write_json(output / 'processing_manifest.json', processing)
    payload = dict(hourly=hourly, summary=summary, associations=associations, validation=report,
        counties=geo, reports=dict(list=report_manifest['reports'], findings=findings, consensus=consensus, discrepancies=discrepancies),
        restoration=restoration_rows, staging=dict(meta=staging_meta, scenarios=staging_summary, points=staging_points,
                     substations=[{k: s[k] for k in ('name', 'city', 'type', 'status', 'max_kv', 'latitude', 'longitude')} for s in substations]),
        drivers=dict(summary=driver_summary, correlations=driver_corr, hotspots=hotspots, recommendations=recs,
                     zip_boundaries=harvey['zip_boundaries'],
                     zips=[{k: r[k] for k in ('zip_code', 'area_name', 'latitude', 'longitude', 'downtime_customer_days_per_customer',
                           'flood_claims_per_1k_customers', 'customers', 'downtime_quartile', 'hotspot', 'small_denominator',
                           'share_claims_high_risk_zone', 'median_water_depth', 'road_km_to_service_center')} for r in driver_rows]),
        harvey=dict(summary=harvey['summary'], county_daily=harvey['county_daily'], damages=harvey['damages']),
        centerpoint=read_csv(raw / 'centerpoint_beryl_milestones.csv'), sources=sources,
        storms=STORMS, generated_at_utc=utc_text(datetime.now(UTC)))
    # External JS assignment allows offline opening via file:// without fetch/CORS.
    dashboard = root / 'dashboard'
    dashboard.mkdir(exist_ok=True)
    (dashboard / 'data.js').write_text('window.STORM_DATA = ' + json.dumps(payload, allow_nan=False) + ';\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ['warnings','checks']}, indent=2))
    return report


CNP_SOURCE = 'https://origin-hmong.centerpointenergy.com/en-us/residential/services/hurricane-beryl-response?sa=mn'

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    build(output=args.output)
