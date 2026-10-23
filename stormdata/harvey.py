"""Harvey-only supplements read from the organizer's ArcGIS geodatabase zips.

* Daily power outages by ZIP code, assigned to counties by sampled ZIP area.
* FEMA modeled housing damage counts by county and floodplain designation.

These are separate sources from EAGLE-I and NFIP. They are kept in their own
files and never merged into the hourly table or the four-storm summary.
"""
import collections
import math
import re

from .common import COUNTIES
from .filegdb import GEOMETRY, GeoDatabase, decode_shape

OUTAGE_ZIP = 'Hurricane_Harvey_Power_Outages_by_Zip_Code.zip'
DAMAGE_ZIP = 'Hurricane_Harvey_FEMA_Modeled_Damages.zip'
OUTAGE_TABLE = 'Hurricane_Harvey_Power_Outages_by_Zip_Code'
DAMAGE_TABLE = 'Hurricane_Harvey_FEMA_Damage_Assessments_by_County_Floodplain_Designation'
GRID = 24              # sample points per side of each ZIP's bounding box
SPLIT_THRESHOLD = 0.9  # below this majority share a ZIP is flagged as split across counties
DAMAGE_COLUMNS = {
    'Affected_Minor_100YR': 'fema_affected_minor_100yr_floodplain',
    'Major_Destroyed_100YR': 'fema_major_destroyed_100yr_floodplain',
    'Affected_Minor_500YR': 'fema_affected_minor_500yr_floodplain',
    'Major_Destroyed_500YR': 'fema_major_destroyed_500yr_floodplain',
    'Affected_Minor_Out_FP': 'fema_affected_minor_outside_floodplain',
    'Major_Destroyed_Out_FP': 'fema_major_destroyed_outside_floodplain',
}


class LambertConformal:
    """Inverse Lambert Conformal Conic (2 standard parallels, ellipsoidal), from an Esri WKT."""
    def __init__(self, wkt):
        if 'Lambert_Conformal_Conic' not in wkt:
            raise ValueError('Expected a Lambert Conformal Conic projection')
        p = {k.lower(): float(v) for k, v in re.findall(r'PARAMETER\["([^"]+)",([-\d.eE]+)\]', wkt)}
        a, inv_f = map(float, re.search(r'SPHEROID\["[^"]+",([\d.]+),([\d.]+)\]', wkt).groups())
        self.unit = float(re.findall(r'UNIT\["[^"]+",([\d.]+)\]', wkt)[-1])
        f = 1 / inv_f
        self.e = e = math.sqrt(2 * f - f * f)
        rad = math.radians
        p1, p2, p0 = rad(p['standard_parallel_1']), rad(p['standard_parallel_2']), rad(p['latitude_of_origin'])
        m = lambda phi: math.cos(phi) / math.sqrt(1 - (e * math.sin(phi)) ** 2)
        self._t = t = lambda phi: math.tan(math.pi / 4 - phi / 2) / ((1 - e * math.sin(phi)) / (1 + e * math.sin(phi))) ** (e / 2)
        self.n = (math.log(m(p1)) - math.log(m(p2))) / (math.log(t(p1)) - math.log(t(p2)))
        self.aF = a * m(p1) / (self.n * t(p1) ** self.n)
        self.rho0 = self.aF * t(p0) ** self.n
        self.lon0 = rad(p['central_meridian'])
        self.fe, self.fn = p['false_easting'] * self.unit, p['false_northing'] * self.unit

    def to_lonlat(self, x, y):
        dx = x * self.unit - self.fe
        dy = self.rho0 - (y * self.unit - self.fn)
        rho = math.copysign(math.hypot(dx, dy), self.n)
        t = (rho / self.aF) ** (1 / self.n)
        lon = math.atan2(dx, dy) / self.n + self.lon0
        e, phi = self.e, math.pi / 2 - 2 * math.atan(t)
        for _ in range(10):
            phi = math.pi / 2 - 2 * math.atan(t * ((1 - e * math.sin(phi)) / (1 + e * math.sin(phi))) ** (e / 2))
        return math.degrees(lon), math.degrees(phi)


def inside(x, y, rings):
    """Even-odd point-in-polygon test over all rings, so holes are excluded."""
    hit = False
    for ring in rings:
        j = len(ring) - 1
        for i in range(len(ring)):
            (xi, yi), (xj, yj) = ring[i], ring[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                hit = not hit
            j = i
    return hit


def county_shapes(geojson):
    shapes = []
    for feature in geojson['features']:
        g = feature['geometry']
        polys = [g['coordinates']] if g['type'] == 'Polygon' else g['coordinates']
        rings = [ring for poly in polys for ring in poly]
        xs, ys = [p[0] for r in rings for p in r], [p[1] for r in rings for p in r]
        shapes.append((feature['properties']['id'], feature['properties']['NAME'], rings, (min(xs), min(ys), max(xs), max(ys))))
    return shapes


def zip_area_shares(parts, project, counties):
    """Share of a ZIP's sampled area falling in each county (and outside all of them)."""
    xs, ys = [p[0] for r in parts for p in r], [p[1] for r in parts for p in r]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    hits, total, sx, sy = collections.Counter(), 0, 0.0, 0.0
    for i in range(GRID):
        for j in range(GRID):
            x, y = x0 + (i + 0.5) * (x1 - x0) / GRID, y0 + (j + 0.5) * (y1 - y0) / GRID
            if not inside(x, y, parts):
                continue
            lon, lat = project.to_lonlat(x, y)
            total, sx, sy = total + 1, sx + lon, sy + lat
            for fips, _, rings, (bx0, by0, bx1, by1) in counties:
                if bx0 <= lon <= bx1 and by0 <= lat <= by1 and inside(lon, lat, rings):
                    hits[fips] += 1
                    break
            else:
                hits[''] += 1
    if not total:  # sliver narrower than the grid: use its first vertex
        lon, lat = project.to_lonlat(*parts[0][0])
        return {next((f for f, _, r, _ in counties if inside(lon, lat, r)), ''): 1.0}, lon, lat, 0
    return {k: v / total for k, v in hits.items()}, sx / total, sy / total, total


def assign_zips(db, geojson):
    field = next(f for f in db.fields(OUTAGE_TABLE) if f.type == GEOMETRY)
    project = LambertConformal(field.extra['wkt'])
    counties = county_shapes(geojson)
    names = {fips: name for fips, name, _, _ in counties}
    shapes = {}
    for row in db.rows(OUTAGE_TABLE, keep_geometry=True):
        shapes.setdefault(row['Zip_Code'], row['Shape'])  # same polygon repeats on each daily row
    out = {}
    for zip_code, blob in sorted(shapes.items()):
        shares, lon, lat, samples = zip_area_shares(decode_shape(blob, field.extra), project, counties)
        best = max(shares, key=lambda k: (shares[k], k))
        if best == '':
            reason = 'majority_outside_supplied_county_boundaries'
        elif best not in COUNTIES:
            reason = 'majority_in_county_outside_study'
        else:
            reason = 'majority_area_in_study_county'
        split = sorted(((k, v) for k, v in shares.items() if k != best and v > 0), key=lambda kv: -kv[1])
        out[zip_code] = dict(zip_code=zip_code, sampled_centroid_longitude=round(lon, 5), sampled_centroid_latitude=round(lat, 5),
            area_samples=samples, majority_county_fips=best, majority_county_name=names.get(best, ''),
            majority_area_share=round(shares[best], 4), split_across_counties=shares[best] < SPLIT_THRESHOLD,
            other_area_shares=';'.join(f'{k or "outside"}:{v:.4f}' for k, v in split),
            study_county_fips=best if best in COUNTIES else '', assignment_reason=reason)
    return out


def outages(db, assignments):
    rows = []
    seen = set()
    for r in db.rows(OUTAGE_TABLE):
        key = (r['Zip_Code'], r['Event_Date'])
        if key in seen:
            raise ValueError(f'Duplicate ZIP-day outage record: {key}')
        seen.add(key)
        d = r['Event_Date']
        if f'{d.month}/{d.day}/{d.year}' != r['Event_Date_String']:
            raise ValueError(f'Outage date disagrees with its text copy on OBJECTID {r["OBJECTID"]}')
        count, customers = r['Outage_Count'], r['Total_Customers']
        for v in (count, customers):
            if v is not None and (v < 0 or not float(v).is_integer()):
                raise ValueError(f'Invalid outage value on OBJECTID {r["OBJECTID"]}')
        a = assignments[r['Zip_Code']]
        rows.append(dict(zip_code=r['Zip_Code'], report_date=d.date().isoformat(),
            outage_count=None if count is None else int(count),
            total_customers=None if customers is None else int(customers),
            source_outage_pct=r['Outage_Pct'],
            outages_exceed_customers=count is not None and customers is not None and count > customers,
            study_county_fips=a['study_county_fips'], majority_area_share=a['majority_area_share'],
            source_objectid=r['OBJECTID']))
    rows.sort(key=lambda r: (r['zip_code'], r['report_date']))
    return rows


def county_daily(zip_rows, assignments):
    groups = collections.defaultdict(list)
    for r in zip_rows:
        if r['study_county_fips']:
            groups[(r['study_county_fips'], r['report_date'])].append(r)
    dates = sorted({r['report_date'] for r in zip_rows})
    out = []
    for fips in COUNTIES:
        assigned = [z for z in assignments.values() if z['study_county_fips'] == fips]
        for date in dates:
            rows = groups[(fips, date)]
            counts = [r['outage_count'] for r in rows if r['outage_count'] is not None]
            customers = [r['total_customers'] for r in rows if r['total_customers'] is not None]
            out.append(dict(county_fips=fips, county_name=COUNTIES[fips], report_date=date,
                zips_assigned=len(assigned), zips_reporting=len(rows),
                split_zips_reporting=sum(assignments[r['zip_code']]['split_across_counties'] for r in rows),
                outage_count_sum=sum(counts) if rows else None,
                reporting_zip_customers_sum=sum(customers) if rows else None,
                outage_pct_of_reporting_zip_customers=round(100 * sum(counts) / sum(customers), 3) if rows and sum(customers) else None,
                zips_with_outages_exceeding_customers=sum(r['outages_exceed_customers'] for r in rows),
                geography='zip_codes_assigned_by_majority_area'))
    return out


def damages(db):
    out = []
    for r in db.rows(DAMAGE_TABLE):
        values = {dest: r[src] for src, dest in DAMAGE_COLUMNS.items()}
        for k, v in values.items():
            if v is None or v < 0 or not float(v).is_integer():
                raise ValueError(f'Invalid FEMA damage value {k} for {r["NAME"]}')
            values[k] = int(v)
        total = int(r['Total_Observations'])
        if sum(values.values()) != total:
            raise ValueError(f'FEMA damage categories do not sum to the total for {r["NAME"]}')
        out.append(dict(county_fips=r['GEOID'], county_name=r['NAME'], in_study_counties=r['GEOID'] in COUNTIES, **values,
            fema_affected_minor_total=sum(v for k, v in values.items() if 'affected_minor' in k),
            fema_major_destroyed_total=sum(v for k, v in values.items() if 'major_destroyed' in k),
            fema_total_observations=total, source_objectid=r['OBJECTID']))
    return sorted(out, key=lambda r: r['county_fips'])


def county_summary(daily, damage_rows):
    damage = {r['county_fips']: r for r in damage_rows}
    out = []
    for fips in COUNTIES:
        rows = [r for r in daily if r['county_fips'] == fips and r['outage_count_sum'] is not None]
        peak = max(rows, key=lambda r: (r['outage_count_sum'], r['report_date']), default=None)
        dmg = damage.get(fips, {})
        out.append(dict(county_fips=fips, county_name=COUNTIES[fips],
            zips_assigned=rows[0]['zips_assigned'] if rows else 0, report_days=len(rows),
            first_report_date=rows[0]['report_date'] if rows else '', last_report_date=rows[-1]['report_date'] if rows else '',
            zip_outage_peak_daily_count=peak['outage_count_sum'] if peak else None,
            zip_outage_peak_date=peak['report_date'] if peak else '',
            zip_outage_peak_pct_of_reporting_customers=peak['outage_pct_of_reporting_zip_customers'] if peak else None,
            reporting_zip_customers_on_peak_date=peak['reporting_zip_customers_sum'] if peak else None,
            fema_affected_minor_total=dmg.get('fema_affected_minor_total'),
            fema_major_destroyed_total=dmg.get('fema_major_destroyed_total'),
            fema_total_observations=dmg.get('fema_total_observations')))
    return out


def zip_boundaries(db):
    """Source ZIP rings in Leaflet latitude/longitude order, including holes and islands."""
    field = next(f for f in db.fields(OUTAGE_TABLE) if f.type == GEOMETRY)
    project = LambertConformal(field.extra['wkt'])
    shapes = {}
    for row in db.rows(OUTAGE_TABLE, keep_geometry=True):
        z = row['Zip_Code']
        if z in shapes:
            continue
        shapes[z] = [[[round(lat, 5), round(lon, 5)]
                      for lon, lat in (project.to_lonlat(x, y) for x, y in ring)]
                     for ring in decode_shape(row['Shape'], field.extra)]
    return shapes


def build_supplement(root, geojson):
    outage_db, damage_db = GeoDatabase(root / OUTAGE_ZIP), GeoDatabase(root / DAMAGE_ZIP)
    assignments = assign_zips(outage_db, geojson)
    zip_rows = outages(outage_db, assignments)
    daily = county_daily(zip_rows, assignments)
    damage_rows = damages(damage_db)
    return dict(zip_assignments=list(assignments.values()), zip_daily=zip_rows, county_daily=daily,
                zip_boundaries=zip_boundaries(outage_db),
                damages=damage_rows, summary=county_summary(daily, damage_rows))
