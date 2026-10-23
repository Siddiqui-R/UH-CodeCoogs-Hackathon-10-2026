"""Independent checks on the exported dataset. Exits nonzero on failure."""
import collections
import json
from datetime import datetime, timedelta
from decimal import Decimal
from .common import ROOT, COUNTIES, STORMS, digest, read_csv


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(root=ROOT):
    p = root / 'data' / 'processed'
    hourly, summary = read_csv(p / 'county_storm_hour.csv'), read_csv(p / 'county_storm.csv')
    keys = [(r['county_fips'], r['storm_event'], r['time_utc']) for r in hourly]
    require(len(keys) == len(set(keys)), 'Duplicate hourly keys')
    require(len(hourly) == len(read_csv(root / 'houston_major_storms_hourly_weather.csv')), 'Weather row conservation failed')
    require(len(summary) == 20, 'Expected 20 county-storm rows')
    skeys = [(r['county_fips'], r['storm_event']) for r in summary]
    require(set(skeys) == {(f, e) for f in COUNTIES for e in STORMS} and len(set(skeys)) == 20, 'Summary key coverage failed')
    require(not any(k.startswith('nfip_') for k in hourly[0]), 'Claims leaked into hourly table')
    groups = collections.defaultdict(list)
    for r in hourly:
        require(r['county_fips'] in COUNTIES, 'Unknown county')
        require(r['time_utc'].endswith('Z'), 'UTC timestamp lacks Z')
        require(datetime.fromisoformat(r['time_local']) == datetime.fromisoformat(r['time_utc'].replace('Z', '+00:00')), 'Local/UTC disagreement')
        n = int(r['outage_observed_quarters'])
        require(0 <= n <= 4, 'Invalid number of quarter-hours')
        require((r['outage_customers_mean_complete_hour'] != '') == (n == 4), 'Partial hour presented as complete')
        require((r['outage_customers_mean_observed'] != '') == (n > 0), 'Absent outage data imputed')
        if n:
            require(abs(float(r['outage_customers_mean_observed']) * n / 4 - float(r['outage_observed_sample_customer_hours'])) < 1e-6, 'Incorrect sample customer-hours')
        groups[(r['county_fips'], r['storm_event'])].append(r)
    source_claims = read_csv(root / 'houston_fema_flood_claims_2017_present.csv')
    audit = read_csv(p / 'claim_assignments.csv')
    require(len(audit) == len(source_claims), 'Claim audit row conservation failed')
    require([int(r['source_row']) for r in audit] == list(range(2, len(source_claims) + 2)), 'Claim audit source rows incorrect')
    claim_groups = collections.defaultdict(list)
    for a in audit:
        if not a['assigned_storm_event']:
            continue
        source = source_claims[int(a['source_row']) - 2]
        event = a['assigned_storm_event']
        spec = STORMS[event]
        require(source['floodEvent'] == spec['claim_label'], 'Wrong claim event label')
        require(spec['claim_start'] <= source['dateOfLoss'][:10] <= spec['claim_end'], 'Claim date outside window')
        require(source['yearOfLoss'] == str(spec['year']), 'Claim year mismatch')
        claim_groups[(source['countyCode'], event)].append(source)
    for r in summary:
        key = (r['county_fips'], r['storm_event'])
        hours, claims = groups[key], claim_groups[key]
        require(int(r['weather_hours']) == len(hours), 'Summary hour count mismatch')
        require(int(r['outage_observed_quarters']) == sum(int(h['outage_observed_quarters']) for h in hours), 'Summary outage sample count mismatch')
        require(int(r['nfip_recorded_claims']) == len(claims), 'Summary claim count mismatch')
        for column, out in [('netBuildingPaymentAmount', 'nfip_building_payment_usd'), ('netContentsPaymentAmount', 'nfip_contents_payment_usd')]:
            values = [Decimal(c[column]) for c in claims if c[column].strip()]
            if values or not claims:
                require(abs(Decimal(r[out]) - sum(values, Decimal(0))) < Decimal('.005'), f'Payment mismatch: {key}, {out}')
            else:
                require(r[out] == '', 'Missing payment fabricated')
        precipitation = [float(h['precipitation_in']) for h in hours if h['precipitation_in']]
        if len(precipitation) == len(hours):
            require(abs(float(r['total_precipitation_in']) - sum(precipitation)) < .0001, 'Precipitation summary mismatch')
    for row in read_csv(p / 'centerpoint_beryl_milestones.csv'):
        require(row['county_fips'] == '', 'CenterPoint territory allocated to county')
        require(row['qualifier'] in ['greater_than', 'nearly', 'reported_rounded'], 'Lost milestone qualifier')
    validate_harvey(root, p)
    validate_evidence(root, p)
    manifest = json.loads((p / 'source_manifest.json').read_text())
    for source in manifest['sources']:
        require(digest(root / source['file']) == source['sha256'], f'Input changed since build: {source["file"]}')
    processing = json.loads((p / 'processing_manifest.json').read_text())
    for name, sha in processing['output_sha256'].items():
        require(digest(p / name) == sha, f'Derived output changed since build: {name}')
    for name, sha in processing['code_sha256'].items():
        require(digest(root / 'stormdata' / name) == sha, f'Pipeline changed since build: {name}')
    print(f'PASS: {len(hourly):,} hourly rows; 20 summaries; claim payments and Harvey supplements reconciled to source; fingerprints verified.')


def validate_evidence(root, p):
    """Report quotes re-verified against page text; consensus and restoration outputs are consistent."""
    from .reports import load
    _, findings = load(root)  # raises if any quote is missing from its stated page
    exported = read_csv(p / 'report_findings.csv')
    require([r['finding_id'] for r in exported] == [f['finding_id'] for f in findings], 'Report findings export differs from curated file')
    for c in read_csv(p / 'report_issue_consensus.csv'):
        ids = c['finding_ids'].split(';')
        reports = {f['report_id'] for f in findings if f['finding_id'] in ids}
        require(int(c['reports_raising']) == len(reports), f'Consensus count wrong for {c["issue_category"]}')
    for r in read_csv(p / 'report_discrepancies.csv'):
        if r['verdict'] != 'not_comparable':
            require(abs(float(r['value_b']) - float(r['value_a']) - float(r['difference_b_minus_a'])) <= 1, f'Discrepancy math wrong: {r["discrepancy_id"]}')
    for r in read_csv(p / 'restoration_metrics.csv'):
        require((r['to_half'] != '') == (r['half_reached'] == 'True'), 'Restoration threshold flag inconsistent')
        require((r['to_tenth'] != '') == (r['tenth_reached'] == 'True'), 'Restoration threshold flag inconsistent')
    restored = {r['zip_code'] for r in read_csv(p / 'harvey_zip_restoration.csv') if r['total_customers_on_peak_date'] not in ('', '0')}
    drivers_rows = read_csv(p / 'zip_downtime_drivers.csv')
    require({r['zip_code'] for r in drivers_rows} == restored, 'Downtime driver ZIPs differ from restoration ZIPs')
    traits = {c['trait'] for c in read_csv(p / 'downtime_driver_correlations.csv')}
    finding_ids = {f['finding_id'] for f in findings}
    for rec in json.loads((p / 'downtime_recommendations.json').read_text())['recommendations']:
        require(set(rec['findings'].split(';')) <= finding_ids, f'Recommendation {rec["id"]} cites a missing finding')
        require(rec['stats'] in traits | {'', 'hotspots'}, f'Recommendation {rec["id"]} cites a missing statistic')
        ids = [x for x in rec['target_ids'].split(';') if x]
        require(ids and len(ids) == rec['target_count'], f'Recommendation {rec["id"]} has no target areas')
        known = {r['zip_code'] for r in drivers_rows} if rec['target_kind'] == 'zips' else set(COUNTIES)
        require(set(ids) <= known, f'Recommendation {rec["id"]} targets an unknown area')
    for s in json.loads((p / 'staging_whatif_summary.json').read_text())['scenarios'].values():
        require(s['best_candidate']['weighted_road_km'] <= s['baseline_weighted_road_km'], 'Adding a site cannot increase travel')
        require(s['baseline_sites'] > 0 and s['demand_points'] > 0, f'Empty what-if scenario {s["scenario"]}')


def validate_harvey(root, p):
    """Reconcile the Harvey supplement files with the source geodatabases."""
    from .filegdb import GeoDatabase
    from .harvey import OUTAGE_ZIP, OUTAGE_TABLE, DAMAGE_ZIP, DAMAGE_TABLE
    source = GeoDatabase(root / OUTAGE_ZIP).rows(OUTAGE_TABLE)
    zip_rows = read_csv(p / 'harvey_zip_outages_daily.csv')
    require(len(zip_rows) == len(source), 'Harvey ZIP outage row conservation failed')
    by_oid = {r['OBJECTID']: r for r in source}
    for r in zip_rows:
        s = by_oid[int(r['source_objectid'])]
        require(r['zip_code'] == s['Zip_Code'] and r['report_date'] == s['Event_Date'].date().isoformat(), 'Harvey ZIP row keys differ from source')
        require(int(r['outage_count']) == s['Outage_Count'] and int(r['total_customers']) == s['Total_Customers'], 'Harvey ZIP counts differ from source')
    assignments = {r['zip_code']: r for r in read_csv(p / 'harvey_zip_county_assignments.csv')}
    require(set(assignments) == {r['Zip_Code'] for r in source}, 'Harvey ZIP assignment coverage failed')
    for a in assignments.values():
        require(a['study_county_fips'] in ('', *COUNTIES), 'Harvey ZIP assigned to unknown county')
        require((a['study_county_fips'] != '') == (a['majority_county_fips'] in COUNTIES), 'Harvey ZIP study-county flag inconsistent')
    sums = collections.Counter()
    for r in zip_rows:
        fips = assignments[r['zip_code']]['study_county_fips']
        require(r['study_county_fips'] == fips, 'Harvey ZIP row county differs from its assignment')
        if fips:
            sums[(fips, r['report_date'])] += int(r['outage_count'])
    daily = read_csv(p / 'harvey_county_outages_daily.csv')
    for r in daily:
        key = (r['county_fips'], r['report_date'])
        if r['outage_count_sum']:
            require(int(r['outage_count_sum']) == sums[key], f'Harvey county daily sum mismatch: {key}')
        else:
            require(key not in sums, f'Harvey county daily value dropped: {key}')
    require(sum(sums.values()) == sum(int(r['outage_count_sum'] or 0) for r in daily), 'Harvey county daily totals not conserved')
    for r in read_csv(p / 'harvey_county_supplement.csv'):
        days = [int(d['outage_count_sum']) for d in daily if d['county_fips'] == r['county_fips'] and d['outage_count_sum']]
        require((int(r['zip_outage_peak_daily_count']) if r['zip_outage_peak_daily_count'] else None) == (max(days) if days else None), 'Harvey peak mismatch')
    damage_source = {r['GEOID']: r for r in GeoDatabase(root / DAMAGE_ZIP).rows(DAMAGE_TABLE)}
    damage = read_csv(p / 'harvey_fema_damage_assessments.csv')
    require({r['county_fips'] for r in damage} == set(damage_source), 'FEMA damage county coverage failed')
    for r in damage:
        require(int(r['fema_total_observations']) == damage_source[r['county_fips']]['Total_Observations'], 'FEMA damage total differs from source')
        require(int(r['fema_affected_minor_total']) + int(r['fema_major_destroyed_total']) == int(r['fema_total_observations']), 'FEMA damage categories do not sum')


if __name__ == '__main__':
    validate()
