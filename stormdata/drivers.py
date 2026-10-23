"""What did long-outage areas have in common? Harvey ZIP-level comparison and recommendations.

Outcome: customer-days without power per customer (daily snapshots summed / customers on the peak day).
Traits come from data already in the build: NFIP flood claims, flood-zone mix, distance to a
service center, ZIP size and location. Rank (Spearman) correlation is the headline statistic, because
a few ZIPs with very few customers produce extreme ratios. Associations only; no causal claim.
"""
import collections
import math
import statistics

from .staging import haversine

SMALL_CUSTOMERS = 500   # ZIPs below this are flagged: ratios are unstable
CLUSTER_KM = 8.0        # high-downtime ZIPs within this distance are grouped into one hotspot

TRAITS = {
    'flood_claims_per_1k_customers': 'Flood insurance claims per 1,000 customers',
    'share_claims_high_risk_zone': 'Share of flood claims in a high-risk flood zone (A/V)',
    'median_water_depth': 'Average water depth in flooded buildings (claims data)',
    'road_km_to_service_center': 'Road km to the nearest service center',
    'customers': 'Customers in the ZIP (size)',
    'latitude': 'Latitude (north to south)',
}

# Common area names for ZIPs that appear in hotspots; used for readable labels only.
AREA_NAMES = {
    '77339': 'Kingwood', '77345': 'Kingwood', '77365': 'Porter', '77357': 'New Caney', '77044': 'Lake Houston area',
    '77346': 'Atascocita', '77338': 'Humble', '77396': 'Humble', '77336': 'Huffman', '77532': 'Crosby',
    '77079': 'Energy Corridor', '77077': 'Energy Corridor', '77094': 'Energy Corridor', '77084': 'Bear Creek',
    '77450': 'Katy', '77449': 'Katy', '77002': 'Downtown Houston', '77081': 'Gulfton', '77389': 'Spring',
    '77373': 'Spring', '77379': 'Spring', '77481': 'Thompsons', '77406': 'Richmond', '77469': 'Richmond',
    '77096': 'Meyerland', '77025': 'Braeswood', '77074': 'Sharpstown', '77036': 'Sharpstown', '77401': 'Bellaire',
    '77024': 'Memorial', '77063': 'Westchase', '77043': 'Spring Branch', '77380': 'The Woodlands', '77381': 'The Woodlands',
    '77010': 'Downtown Houston', '77020': 'Fifth Ward', '77013': 'Northshore', '77049': 'Sheldon', '77316': 'Montgomery', '77385': 'Conroe', '77515': 'Angleton', '77039': 'Aldine',
    '77554': 'Galveston', '77417': 'Beasley', '77386': 'Spring', '77471': 'Rosenberg', '77563': 'Hitchcock', '77573': 'League City', '77598': 'Webster', '77546': 'Friendswood', '77584': 'Pearland',
}


def ranks(values):
    """Average ranks, so ties share a rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2
        i = j + 1
    return out


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx, syy = sum((x - mx) ** 2 for x in xs), sum((y - my) ** 2 for y in ys)
    return round(sxy / math.sqrt(sxx * syy), 4) if sxx and syy else None


def spearman(xs, ys):
    return pearson(ranks(xs), ranks(ys))


def quartiles(rows, key):
    ordered = sorted(rows, key=lambda r: (r[key], r['zip_code']))
    q = len(ordered) // 4
    for i, r in enumerate(ordered):
        r['downtime_quartile'] = min(4, i // q + 1) if q else 1
    return ordered[:q], ordered[-q:]


def clusters(points, km):
    """Single-link grouping of points within km of each other."""
    groups, seen = [], set()
    for p in points:
        if p['zip_code'] in seen:
            continue
        group, stack = [], [p]
        seen.add(p['zip_code'])
        while stack:
            cur = stack.pop()
            group.append(cur)
            for q in points:
                if q['zip_code'] not in seen and haversine(cur['latitude'], cur['longitude'], q['latitude'], q['longitude']) <= km:
                    seen.add(q['zip_code'])
                    stack.append(q)
        groups.append(group)
    return groups


def zip_rows(zip_restoration, assignments, staging_points, claim_rows):
    claims = collections.defaultdict(list)
    for c in claim_rows:
        if c['floodEvent'] == 'Hurricane Harvey' and c['reportedZipCode'].strip():
            claims[c['reportedZipCode'].strip()[:5]].append(c)
    where = {a['zip_code']: a for a in assignments}
    dist = {p['point_id'][4:]: p['road_km_to_nearest_site'] for p in staging_points if p['scenario'] == 'power'}
    rows = []
    for r in zip_restoration:
        z, customers = r['zip_code'], r['total_customers_on_peak_date']
        if not customers:
            continue
        cl = claims.get(z, [])
        depths = [float(c['waterDepth']) for c in cl if c['waterDepth'].strip()]
        a = where[z]
        rows.append(dict(zip_code=z, area_name=AREA_NAMES.get(z, ''), county_name=a['majority_county_name'] or 'Outside supplied counties',
            latitude=a['sampled_centroid_latitude'], longitude=a['sampled_centroid_longitude'],
            downtime_customer_days_per_customer=round(r['customer_days_out_snapshot_sum'] / customers, 5),
            days_peak_to_half=r['days_peak_to_half'], customers=customers, harvey_flood_claims=len(cl),
            flood_claims_per_1k_customers=round(1000 * len(cl) / customers, 3),
            share_claims_high_risk_zone=round(sum(c['ratedFloodZone'].strip()[:1] in ('A', 'V') for c in cl) / len(cl), 4) if cl else 0.0,
            median_water_depth=statistics.median(depths) if depths else 0.0,
            road_km_to_service_center=dist[z], small_denominator=customers < SMALL_CUSTOMERS))
    return rows


def analyse(rows):
    y = 'downtime_customer_days_per_customer'
    low, high = quartiles(rows, y)
    corr = []
    for trait, label in TRAITS.items():
        xs, ys = [r[trait] for r in rows], [r[y] for r in rows]
        # Depth is mostly whole numbers, so medians tie; the mean shows the difference between groups.
        center = statistics.mean if trait == 'median_water_depth' else statistics.median
        lo_m, hi_m = center(r[trait] for r in low), center(r[trait] for r in high)
        corr.append(dict(trait=trait, label=label, n=len(rows), spearman_r=spearman(xs, ys), pearson_r=pearson(xs, ys),
            low_downtime_median=round(lo_m, 4), high_downtime_median=round(hi_m, 4),
            high_over_low=round(hi_m / lo_m, 2) if lo_m else None))
    corr.sort(key=lambda c: -abs(c['spearman_r'] or 0))
    # Hotspots: top-quartile ZIPs grouped by proximity.
    hot = []
    # Tiny ZIPs give unstable ratios, so they are kept in the table but not used to define hotspots.
    groups = sorted(clusters([r for r in high if not r['small_denominator']], CLUSTER_KM), key=lambda g: -statistics.median(r[y] for r in g))
    for i, g in enumerate(groups, 1):
        named = sorted((r for r in g if r['area_name']), key=lambda r: -r[y])
        label = named[0]['area_name'] if named else f'ZIP {max(g, key=lambda r: r[y])["zip_code"]} area'
        for r in g:
            r['hotspot'] = f'H{i}'
        hot.append(dict(hotspot=f'H{i}', label=label, zips=';'.join(sorted(r['zip_code'] for r in g)), zip_count=len(g),
            counties=';'.join(sorted({r['county_name'] for r in g})),
            latitude=round(statistics.mean(r['latitude'] for r in g), 4), longitude=round(statistics.mean(r['longitude'] for r in g), 4),
            customers=sum(r['customers'] for r in g),
            customer_days_out=round(sum(r[y] * r['customers'] for r in g)),
            median_downtime=round(statistics.median(r[y] for r in g), 4),
            median_flood_claims_per_1k=round(statistics.median(r['flood_claims_per_1k_customers'] for r in g), 2)))
    for r in rows:
        r.setdefault('hotspot', '')
    summary = dict(n_zips=len(rows), quartile_size=len(low),
                   low_median_downtime=round(statistics.median(r[y] for r in low), 4),
                   high_median_downtime=round(statistics.median(r[y] for r in high), 4))
    return corr, hot, summary


def recommendations(corr, hot, summary, staging_scenarios):
    c = {x['trait']: x for x in corr}
    flood, dist, size = c['flood_claims_per_1k_customers'], c['road_km_to_service_center'], c['customers']
    top = hot[:3]
    places = ', '.join(f"{AREA_NAMES.get(z, 'ZIP area')} ({z})" for h in top for z in h['zips'].split(';'))
    return [
        dict(id='R1', title='Flood-proof the grid where flood claims concentrate', strength='Strongest signal in the data',
             evidence=f"ZIPs with the longest outages had {flood['high_over_low']:.1f}× the flood-claim rate of the fastest-restored ZIPs "
                      f"({flood['high_downtime_median']:.0f} vs {flood['low_downtime_median']:.0f} claims per 1,000 customers; rank correlation {flood['spearman_r']:+.2f}, {flood['n']} ZIPs).",
             action='Elevate or flood-harden substations and pad-mounted equipment in the hotspot ZIPs, and pre-stage mobile generation on high ground beside them before landfall.',
             findings='F50;F44;F06', stats='flood_claims_per_1k_customers'),
        dict(id='R2', title='Start with the named hotspots', strength='Located from the data',
             evidence=f"The longest outages clustered in {places}.",
             action='Make these the first areas for hardening, pre-staged crews and mobile generation, and keep relief supplies on high ground inside each cluster.',
             findings='F15;F44', stats='hotspots'),
        dict(id='R3', title='Clear roads and restore information first', strength='Data plus 4 reports',
             evidence=f"Distance to a service center did not separate long and short outages (rank correlation {abs(dist['spearman_r']):.2f}). Reports point to blocked roads and missing outage information instead.",
             action='Pair crew staging with debris-clearing crews on access routes, and keep a working outage map and call line from hour one.',
             findings='F16;F03;F04;F05', stats='road_km_to_service_center'),
        dict(id='R4', title='Segment circuits serving smaller and outlying areas', strength='Data agrees with the regulator',
             evidence=f"Smaller ZIPs ran slightly longer outages (rank correlation {size['spearman_r']:+.2f} with customer count), as the PUCT found for less-populated areas and single-line service.",
             action='Add sectionalizers and automatic reclosers so one fault no longer darkens a whole outlying feeder.',
             findings='F48;F49', stats='customers'),
        dict(id='R5', title='For wind storms like Beryl, target trees', strength='Supported by 3 reports; ZIP data to confirm',
             evidence='CenterPoint found its longest Beryl outages where rainfall and vegetation were highest, and the PUCT found most tree damage came from outside utility rights-of-way.',
             action='Create a way for residents to report hazard trees, trim beyond rights-of-way with owner consent, and collect circuit-level canopy data so the next storm can be measured ZIP by ZIP.',
             findings='F30;F09;F10', stats=''),
    ]


DOWNTOWN = (29.7604, -95.3698)   # City Hall area, used to define 'outlying'
OUTLYING_KM = 25.0


def pct(values, p):
    v = sorted(values)
    return v[int(p * (len(v) - 1))]


def place_names(zrows, limit=6):
    names = []
    for r in sorted(zrows, key=lambda r: -r['downtime_customer_days_per_customer']):
        label = r['area_name'] or f"ZIP {r['zip_code']}"
        if label not in names:
            names.append(label)
    return ', '.join(names[:limit]) + (f' and {len(names) - limit} more' if len(names) > limit else '')


def targets(rows, hot, restoration_rows):
    """Where each recommendation applies, chosen from the data by a stated rule."""
    y = 'downtime_customer_days_per_customer'
    ok = [r for r in rows if not r['small_denominator']]
    dt75, dt50 = pct([r[y] for r in ok], .75), pct([r[y] for r in ok], .5)
    fc75, fc50 = pct([r['flood_claims_per_1k_customers'] for r in ok], .75), pct([r['flood_claims_per_1k_customers'] for r in ok], .5)
    cu25 = pct([r['customers'] for r in ok], .25)
    out = {}

    def zips(rec, chosen, rule):
        out[rec] = dict(target_kind='zips', target_ids=';'.join(r['zip_code'] for r in chosen), target_count=len(chosen),
                        target_places=place_names(chosen), target_rule=rule)

    zips('R1', [r for r in ok if r[y] >= dt75 and r['flood_claims_per_1k_customers'] >= fc75],
         f'Slowest-restored quarter of ZIPs (at least {dt75:.2f} days out per customer) that are also in the top quarter for flood claims (at least {fc75:.0f} per 1,000 customers).')
    hz = {z for h in hot[:3] for z in h['zips'].split(';')}
    zips('R2', [r for r in ok if r['zip_code'] in hz],
         'The three hotspot clusters: slowest-quarter ZIPs within 8 km of each other, ranked by median outage length.')
    zips('R3', [r for r in ok if r[y] >= dt75 and r['flood_claims_per_1k_customers'] < fc50],
         f'Slowest-restored quarter of ZIPs with below-median flood claims (under {fc50:.0f} per 1,000 customers). These are access-review candidates; the data does not identify blocked roads or establish the cause of each outage.')
    zips('R4', [r for r in ok if r['customers'] <= cu25 and r[y] >= dt50
                and haversine(r['latitude'], r['longitude'], *DOWNTOWN) > OUTLYING_KM],
         f'Smaller ZIPs (bottom quarter, up to {cu25:,.0f} customers) more than {OUTLYING_KM:.0f} km from downtown Houston with slower-than-median restoration.')
    beryl = [r for r in restoration_rows if r['storm_event'] == 'Hurricane_Beryl_2024' and r['to_half'] is not None]
    med = statistics.median(r['to_half'] for r in beryl)
    slow = sorted((r for r in beryl if r['to_half'] >= med), key=lambda r: -r['to_half'])
    out['R5'] = dict(target_kind='counties', target_ids=';'.join(r['county_fips'] for r in slow), target_count=len(slow),
                     target_places=', '.join(f"{r['county_name']} ({r['to_half']} hours)" for r in slow),
                     target_rule=f'Counties that took at least the median {med:g} hours to halve Beryl outages (EAGLE-I). Beryl outage data exists only by county.',
                     county_hours={r['county_fips']: r['to_half'] for r in beryl})
    return out


def build(zip_restoration, assignments, staging_points, claim_rows, staging_scenarios, restoration_rows):
    rows = zip_rows(zip_restoration, assignments, staging_points, claim_rows)
    corr, hot, summary = analyse(rows)
    recs = recommendations(corr, hot, summary, staging_scenarios)
    where = targets(rows, hot, restoration_rows)
    for r in recs:
        r.update(where[r['id']])
    return rows, corr, hot, summary, recs
