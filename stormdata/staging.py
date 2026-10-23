"""Facility what-if for Harvey, in three scenarios.

power  - utility crews from CenterPoint service centers to ZIPs weighted by customer-days without power
flood  - flood relief from the Harvey mega-shelters to NFIP flood-claim locations (0.1 degree cells)
relief - general disaster relief from shelters and responder staging to a combined need index
         (half the region's outage burden, half its flood claims)

Trip = straight-line km x road circuity, converted to minutes at an assumed storm-period speed.
"""
import collections
import math

from .common import COUNTIES

ROAD_CIRCUITY = 1.3     # road km per straight-line km (assumption; typical urban values ~1.2-1.4)
STORM_SPEED_KMH = 30.0  # assumed average driving speed with debris and closures
GRID_STEP_DEG = 0.05    # candidate-site spacing (~5 km)
MAX_CANDIDATE_GAP_KM = 8.0  # candidates must sit near demand

SCENARIOS = {
    'relief': dict(label='Disaster relief', facility='shelters and responder staging',
                   demand='combined need: half outage burden, half flood claims', unit='need points'),
    'power': dict(label='Power outages', facility='utility service centers',
                  demand='customer-days without power (Harvey ZIP file)', unit='customer-days'),
    'flood': dict(label='Flood relief', facility='mega-shelters',
                  demand='Harvey NFIP flood claims', unit='claims'),
}


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = p2 - p1, math.radians(lon2 - lon1)
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2)))


def nearest(point, sites):
    return min((haversine(point['lat'], point['lon'], s['lat'], s['lon']), s['site_id']) for s in sites)


def weighted_access(demand, sites):
    total = sum(d['weight'] for d in demand)
    km = sum(d['weight'] * nearest(d, sites)[0] for d in demand) / total * ROAD_CIRCUITY
    return dict(weighted_road_km=round(km, 2), weighted_travel_minutes=round(km / STORM_SPEED_KMH * 60, 1))


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx, syy = sum((x - mx) ** 2 for x in xs), sum((y - my) ** 2 for y in ys)
    return round(sxy / math.sqrt(sxx * syy), 4) if sxx and syy else None


def power_demand(assignments, zip_restoration):
    rec = {r['zip_code']: r for r in zip_restoration}
    out = []
    for a in assignments:
        r = rec[a['zip_code']]
        if r['customer_days_out_snapshot_sum'] > 0:
            out.append(dict(point_id=f'zip_{a["zip_code"]}', label=f'ZIP {a["zip_code"]}', lat=a['sampled_centroid_latitude'],
                            lon=a['sampled_centroid_longitude'], weight=r['customer_days_out_snapshot_sum'],
                            days_peak_to_half=r['days_peak_to_half'], half_reached=r['half_reached']))
    return out


def flood_demand(claims):
    cells = collections.Counter()
    for c in claims:
        if c['floodEvent'] == 'Hurricane Harvey' and c['countyCode'] in COUNTIES and c['latitude'] and c['longitude']:
            cells[(round(float(c['latitude']), 1), round(float(c['longitude']), 1))] += 1
    return [dict(point_id=f'cell_{lat}_{lon}', label=f'Claims cell {lat}, {lon}', lat=lat, lon=lon, weight=n)
            for (lat, lon), n in sorted(cells.items())]


def combined_demand(power, flood):
    tp, tf = sum(d['weight'] for d in power), sum(d['weight'] for d in flood)
    out = [dict(d, weight=round(50000 * d['weight'] / tp, 3)) for d in power]
    out += [dict(d, weight=round(50000 * d['weight'] / tf, 3)) for d in flood]
    return out


def candidates(demand):
    lats, lons = [d['lat'] for d in demand], [d['lon'] for d in demand]
    out = []
    lat = math.floor(min(lats) / GRID_STEP_DEG) * GRID_STEP_DEG
    while lat <= max(lats):
        lon = math.floor(min(lons) / GRID_STEP_DEG) * GRID_STEP_DEG
        while lon <= max(lons):
            if min(haversine(lat, lon, d['lat'], d['lon']) for d in demand) <= MAX_CANDIDATE_GAP_KM:
                out.append(dict(site_id=f'cand_{lat:.2f}_{lon:.2f}', lat=round(lat, 4), lon=round(lon, 4)))
            lon += GRID_STEP_DEG
        lat += GRID_STEP_DEG
    return out


def run(key, sites, demand):
    base = weighted_access(demand, sites)
    results = []
    for c in candidates(demand):
        after = weighted_access(demand, sites + [c])
        results.append(dict(scenario=key, candidate_id=c['site_id'], latitude=c['lat'], longitude=c['lon'], **after,
            minutes_saved=round(base['weighted_travel_minutes'] - after['weighted_travel_minutes'], 1),
            pct_travel_reduction=round(100 * (1 - after['weighted_road_km'] / base['weighted_road_km']), 1)))
    results.sort(key=lambda r: (-r['minutes_saved'], r['candidate_id']))
    points = [dict(scenario=key, point_id=d['point_id'], label=d['label'], latitude=d['lat'], longitude=d['lon'],
                   weight=d['weight'], nearest_site=nearest(d, sites)[1],
                   road_km_to_nearest_site=round(nearest(d, sites)[0] * ROAD_CIRCUITY, 2)) for d in demand]
    summary = dict(scenario=key, **SCENARIOS[key], baseline_sites=len(sites), demand_points=len(demand),
                   **{f'baseline_{k}': v for k, v in base.items()}, best_candidate=results[0])
    return summary, results, points


def what_if(sites_rows, assignments, zip_restoration, claims):
    # Official sites form today's baseline; unofficial ones are kept apart so their effect can be shown separately.
    sites = {k: [] for k in SCENARIOS}
    unofficial = {k: [] for k in SCENARIOS}
    for s in sites_rows:
        site = dict(site_id=s['site_id'], name=s['name'], lat=float(s['latitude']), lon=float(s['longitude']),
                    site_type=s['site_type'], operator=s['operator'], source=s['list_source'], note=s['note'])
        for key in s['scenario'].split(';'):
            (sites if s.get('status', 'official') == 'official' else unofficial)[key].append(site)
    power = power_demand(assignments, zip_restoration)
    flood = flood_demand(claims)
    demand = dict(power=power, flood=flood, relief=combined_demand(power, flood))
    out, all_candidates, all_points = {}, [], []
    for key in SCENARIOS:
        summary, results, points = run(key, sites[key], demand[key])
        summary['sites'] = sites[key]
        summary['unofficial_sites'] = unofficial[key]
        if unofficial[key]:
            summary['with_unofficial'] = weighted_access(demand[key], sites[key] + unofficial[key])
        summary['top_candidates'] = results[:10]
        out[key] = summary
        all_candidates += results
        all_points += points
    # Restoration-speed check for the power scenario: does distance track days to halve outages?
    dist = {p['point_id']: p['road_km_to_nearest_site'] for p in all_points if p['scenario'] == 'power'}
    timed = [d for d in power if d['half_reached'] and d['days_peak_to_half'] is not None]
    r = pearson([dist[d['point_id']] for d in timed], [d['days_peak_to_half'] for d in timed])
    out['power']['evidence'] = dict(n_zips_timed=len(timed), r_distance_vs_days_to_half=r,
                                    supports_distance_effect=bool(r is not None and r >= 0.2 and len(timed) >= 30))
    meta = dict(road_circuity=ROAD_CIRCUITY, storm_speed_kmh=STORM_SPEED_KMH, grid_step_deg=GRID_STEP_DEG, order=list(SCENARIOS))
    return out, meta, all_candidates, all_points
