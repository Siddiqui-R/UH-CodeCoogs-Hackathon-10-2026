"""Official report evidence: verified quotes, issue consensus, and discrepancy checks.

Findings are hand-curated in data/raw/reports/report_findings.csv. Every quote must
appear on the stated page of the report's extracted text, or the build fails.
"""
import collections
import json
import re
from datetime import datetime

from .common import UTC, read_csv

ISSUE_LABELS = {
    'communication_information': 'Customers and responders could not get reliable information',
    'vegetation_trees': 'Trees and vegetation caused most of the damage',
    'staging_logistics': 'Crew staging, travel and coordination slowed restoration',
    'critical_facilities_backup_power': 'Critical facilities lacked backup power or priority contact',
    'resource_planning': 'Planning underestimated what the storm needed',
    'restoration_speed': 'Restoration took many days',
    'infrastructure_hardening': 'Grid hardening did not prevent widespread failure',
    'outage_scale': 'Outage scale',
    'heat_health': 'Heat and health harm during outages',
}


def normalize(text):
    text = text.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    return re.sub(r'\s+', ' ', text).strip()


def page_texts(path):
    pages, current = {}, None
    for line in path.read_text(encoding='utf-8').splitlines():
        m = re.match(r'=== PAGE (\d+) ===$', line)
        if m:
            current = int(m.group(1))
            pages[current] = []
        elif current is not None:
            pages[current].append(line)
    return {k: normalize(' '.join(v)) for k, v in pages.items()}


def load(root):
    folder = root / 'data' / 'raw' / 'reports'
    manifest = json.loads((folder / 'reports.json').read_text(encoding='utf-8'))
    reports = {r['report_id']: r for r in manifest['reports']}
    findings = read_csv(folder / 'report_findings.csv')
    texts = {rid: page_texts(folder / 'text' / (r['file'][:-4] + '.txt')) for rid, r in reports.items()}
    ids = set()
    for f in findings:
        if f['finding_id'] in ids:
            raise ValueError(f'Duplicate finding {f["finding_id"]}')
        ids.add(f['finding_id'])
        if f['report_id'] not in reports:
            raise ValueError(f'{f["finding_id"]}: unknown report {f["report_id"]}')
        if f['issue_category'] not in ISSUE_LABELS:
            raise ValueError(f'{f["finding_id"]}: unknown issue {f["issue_category"]}')
        page = texts[f['report_id']].get(int(f['page']), '')
        if normalize(f['quote']) not in page:
            raise ValueError(f'{f["finding_id"]}: quote not found on page {f["page"]} of {f["report_id"]}')
        report = reports[f['report_id']]
        f.update(storm=report['storm'], publisher=report['publisher'], publisher_type=report['publisher_type'],
                 source_url=report['source_url'], quote_verified=True)
        f['metric_value'] = float(f['metric_value']) if f['metric_value'] else None
    return manifest, findings


def consensus(findings, reports):
    by_issue = collections.defaultdict(list)
    for f in findings:
        by_issue[f['issue_category']].append(f)
    total = len(reports)
    out = []
    for issue, rows in by_issue.items():
        rids = sorted({r['report_id'] for r in rows})
        types = sorted({r['publisher_type'] for r in rows})
        storms = sorted({r['storm'] for r in rows})
        out.append(dict(issue_category=issue, issue_label=ISSUE_LABELS[issue], reports_raising=len(rids), reports_total=total,
            report_ids=';'.join(rids), publisher_types=';'.join(types), storms=';'.join(storms),
            raised_in_both_storms=len(storms) > 1, utility_and_regulator_agree='utility' in types and 'state_regulator' in types,
            finding_ids=';'.join(r['finding_id'] for r in rows)))
    return sorted(out, key=lambda r: (-r['reports_raising'], -len(r['finding_ids'].split(';')), r['issue_category']))


def _utc(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00'))


def eaglei_five_county(hourly, storm, when_utc):
    """Five-county EAGLE-I sum for the hour containing when_utc; None unless all five counties observed."""
    key = when_utc.replace(minute=0, second=0, microsecond=0)
    rows = [r for r in hourly if r['storm_event'] == storm and _utc(r['time_utc']) == key]
    values = [r['outage_customers_mean_observed'] for r in rows]
    if len(rows) != 5 or any(v is None for v in values):
        return None
    return round(sum(values))


def compare(did, storm, topic, kind, a, b, note):
    va, vb = a['value'], b['value']
    if va is None or vb is None:
        verdict, diff, ratio = 'not_comparable', None, None
    else:
        diff, ratio = round(vb - va), round(vb / va, 3) if va else None
        if a['unit'] != b['unit']:
            verdict = 'unit_mismatch'
        elif a.get('scope') != b.get('scope'):
            verdict = 'different_geography'
        else:
            verdict = 'agree_within_10pct' if ratio is not None and abs(ratio - 1) <= 0.10 else 'disagree'
    return dict(discrepancy_id=did, storm=storm, topic=topic, comparison=kind,
        source_a=a['source'], value_a=va, unit_a=a['unit'], scope_a=a.get('scope', ''),
        source_b=b['source'], value_b=vb, unit_b=b['unit'], scope_b=b.get('scope', ''),
        difference_b_minus_a=diff, ratio_b_over_a=ratio, verdict=verdict, note=note)


def discrepancies(findings, hourly, centerpoint, harvey_county_daily, harvey_zip_daily, summary):
    f = {r['finding_id']: r for r in findings}

    def rep(fid):
        r = f[fid]
        return dict(source=f'{r["publisher"]}, p.{r["page"]} ({fid})', value=r['metric_value'], unit=r['metric_unit'], scope=r['metric_scope'])

    def eaglei(when_local, label):
        when = datetime.fromisoformat(when_local)
        return dict(source=f'EAGLE-I, 5 study counties, {label}', value=eaglei_five_county(hourly, 'Hurricane_Beryl_2024', when.astimezone(UTC)),
                    unit='customers', scope='five_study_counties')

    B, H = 'Hurricane_Beryl_2024', 'Hurricane_Harvey_2017'
    out = [
        compare('D01', B, 'CenterPoint customers out at peak', 'report_vs_report', rep('F02'), rep('F11'),
            'PUCT gives 2.2M in its summary but cites PA Consulting for "more than 2.1M" later in the same report.'),
        compare('D02', B, 'CenterPoint outage scale: customers vs people', 'report_vs_report', rep('F02'), rep('F27'),
            'CenterPoint says "people impacted" where the PUCT says customers. A customer is a meter, often a household of several people, so these are different measures that look alike.'),
        compare('D03', B, 'Regional peak: customers vs people', 'report_vs_report', rep('F01'), rep('F34'),
            'NWS reports the same 2.7M figure as "people"; the PUCT reports it as customers. One of the two labels is wrong.'),
        compare('D04', B, 'Workforce: model forecast vs actual', 'report_vs_report', rep('F19'), rep('F20'),
            "CenterPoint's damage model (built on 2008 Ike data) forecast at most 2,559 workers; about 14,000 were needed."),
        compare('D05', B, 'Staging sites: used vs recommended', 'report_vs_report', rep('F17'), rep('F18'),
            'PUCT recommends planning for 25-30 staging areas (lower bound shown); CenterPoint used 22.'),
        compare('D06', B, 'Peak outages: PUCT statewide vs EAGLE-I study counties', 'report_vs_data', rep('F01'),
            dict(source='EAGLE-I, 5 study counties combined, peak hour', value=max(
                    (v for v in (eaglei_five_county(hourly, B, _utc(t)) for t in {r['time_utc'] for r in hourly if r['storm_event'] == B}) if v is not None), default=None),
                 unit='customers', scope='five_study_counties'),
            'Five counties are a subset of the state, so EAGLE-I should be somewhat lower. A ratio near 0.9 means the sources are consistent.'),
        compare('D07', B, 'Outages Jul 9 9 a.m.: PUCT vs EAGLE-I', 'report_vs_data', rep('F22'), eaglei('2024-07-09T09:00:00-05:00', 'Jul 9 09:00'),
            'Statewide vs five counties; consistent if the ratio stays near the peak ratio.'),
        compare('D08', B, 'Outages Jul 10 morning: PUCT vs EAGLE-I', 'report_vs_data', rep('F23'), eaglei('2024-07-10T09:00:00-05:00', 'Jul 10 09:00'),
            'PUCT gives "morning"; EAGLE-I shown at 09:00 local.'),
        compare('D09', B, 'Outages Jul 11: PUCT vs EAGLE-I', 'report_vs_data', rep('F24'), eaglei('2024-07-11T09:00:00-05:00', 'Jul 11 09:00'),
            'PUCT gives a date only; EAGLE-I shown at 09:00 local.'),
        compare('D10', B, 'Still out 4 days later: NWS (people) vs EAGLE-I (customers)', 'report_vs_data', rep('F35'), eaglei('2024-07-12T09:00:00-05:00', 'Jul 12 09:00'),
            'NWS counts "people"; EAGLE-I counts customers. The numbers match only if NWS meant customers.'),
    ]
    # CenterPoint's own milestones imply how many of its customers were still out; compare with EAGLE-I.
    peak = f['F02']['metric_value']
    n = 11
    for m in centerpoint:
        if m['metric'] != 'customers_restored':
            continue
        when = _utc(m['report_time_utc'])
        implied = dict(source=f'CenterPoint release {m["report_time_local"][:16]} ({m["qualifier"]} {int(float(m["reported_value"])):,} restored) vs PUCT 2.2M peak',
                       value=peak - float(m['reported_value']), unit='customers', scope='centerpoint_territory')
        observed = dict(source=f'EAGLE-I, 5 study counties, {m["report_time_local"][:16]}', value=eaglei_five_county(hourly, B, when),
                        unit='customers', scope='five_study_counties')
        note = ('Outside the EAGLE-I extract window (ends Jul 12 23:00 local).' if observed['value'] is None else
                'EAGLE-I includes other utilities in the five counties (Entergy, TNMP, co-ops), so it should be somewhat higher. A gap far above that suggests CenterPoint figures run ahead of metered outages.')
        out.append(compare(f'D{n:02d}', B, 'Still out: CenterPoint-implied vs EAGLE-I', 'report_vs_data', implied, observed, note))
        n += 1
    # Harvey: statewide report vs the two outage datasets.
    aug26 = [r for r in harvey_zip_daily if r['report_date'] == '2017-08-27']
    out.append(compare(f'D{n:02d}', H, 'Harvey outages: Eye of the Storm vs ZIP file', 'report_vs_data', rep('F42'),
        dict(source='ZIP outage file, all 198 ZIPs, 2017-08-27 (first day in file)', value=sum(r['outage_count'] for r in aug26), unit='customers', scope='houston_zip_codes'),
        'Report is statewide on Aug 26; the ZIP file starts Aug 27 and covers 198 Houston-area ZIPs only.'))
    n += 1
    harris = next(r for r in summary if r['storm_event'] == H and r['county_fips'] == '48201')
    harris_zip = max((r['outage_count_sum'] or 0) for r in harvey_county_daily if r['county_fips'] == '48201')
    out.append(compare(f'D{n:02d}', H, 'Harris County Harvey peak: EAGLE-I vs ZIP file', 'data_vs_data',
        dict(source='EAGLE-I, Harris, peak quarter-hour', value=harris['outage_peak_customers_observed'], unit='customers', scope='harris_county'),
        dict(source='ZIP outage file, Harris ZIPs, peak daily snapshot', value=harris_zip, unit='customers', scope='harris_county'),
        'Two outage datasets for the same county and storm; the ratio shows how incomplete 2017 EAGLE-I coverage was.'))
    return out
