"""Fetch official EAGLE-I subsets using validated HTTP byte ranges, plus CNP evidence.

No credentials, third-party mirrors, or synthetic outage records are used.
"""
import concurrent.futures
import csv
import hashlib
import io
import json
import re
import time
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from .common import ROOT, COUNTIES, STORMS, UTC, read_csv, utc_text, weather_windows, write_csv, write_json

ARTICLE = 'https://api.figshare.com/v2/articles/24237376/versions/4'
CNP_URL = 'https://origin-hmong.centerpointenergy.com/en-us/residential/services/hurricane-beryl-response?sa=mn'
RAW = ROOT / 'data' / 'raw'


def centerpoint_milestones(html):
    class Text(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
        def handle_data(self, data):
            self.parts.append(data)
    parser = Text()
    parser.feed(html)
    text = ' '.join(' '.join(parser.parts).split())
    entries = {}
    pattern = r'July\s+(\d{1,2}),\s+2024\s*-\s*(\d{1,2}):(\d{2})\s*(a|p)\.m\.\s*-\s*'
    matches = list(re.finditer(pattern, text))
    for i, match in enumerate(matches):
        day, hour, minute, period = match.groups()
        hour = int(hour) % 12 + (12 if period == 'p' else 0)
        stamp = f'2024-07-{int(day):02d}T{hour:02d}:{minute}:00-05:00'
        entries[stamp] = text[match.end():matches[i+1].start() if i+1<len(matches) else len(text)]
    specs = [
        ('2024-07-09T15:30:00-05:00', 'customers_restored', 640000, 'greater_than', 'more than 640,000'),
        ('2024-07-10T13:45:00-05:00', 'customers_restored', 1000000, 'nearly', 'nearly 1 million'),
        ('2024-07-12T12:00:00-05:00', 'customers_restored', 1400000, 'greater_than', 'more than 1.4 million'),
        ('2024-07-13T14:00:00-05:00', 'customers_restored', 1600000, 'greater_than', 'more than 1.6 million'),
        ('2024-07-13T20:00:00-05:00', 'percent_impacted_restored', 80, 'reported_rounded', '80% of impacted'),
        ('2024-07-15T08:00:00-05:00', 'customers_restored', 2000000, 'greater_than', 'over 2 million'),
        ('2024-07-15T20:00:00-05:00', 'percent_impacted_restored', 92, 'reported_rounded', '92% of impacted'),
        ('2024-07-17T11:30:00-05:00', 'percent_impacted_restored', 98, 'greater_than', 'more than 98%'),
    ]
    out = []
    for stamp, metric, value, qualifier, phrase in specs:
        if phrase.lower() not in entries.get(stamp, '').lower():
            raise ValueError(f'CenterPoint dated headline changed: {stamp}: {phrase}')
        out.append(dict(storm_event='Hurricane_Beryl_2024', report_time_local=stamp,
            report_time_utc=utc_text(datetime.fromisoformat(stamp)), metric=metric, reported_value=value,
            qualifier=qualifier, geography='CenterPoint Houston Electric service territory',
            county_fips='', status='company_reported_at_publication_not_independently_reconciled',
            timestamp_meaning='release_publication_time_not_exact_measurement_time',
            source_phrase=phrase, source_url=CNP_URL))
    return out


def get(url, headers=None):
    for attempt in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=60)
        except Exception:
            if attempt == 3:
                raise
            time.sleep(attempt + 1)


class RangeCSV:
    def __init__(self, file, key):
        self.file, self.key = file, key
        self.size = file['size']
        self.ranges = []
        head = self.block(0, 8191)
        self.fields = next(csv.reader([head.splitlines()[0].decode('utf-8-sig')]))

    def block(self, start, end):
        end = min(end, self.size - 1)
        url = self.file['download_url'] + f'?range={start}-{end}'
        with get(url, {'Range': f'bytes={start}-{end}'}) as r:
            expected = f'bytes {start}-{end}/{self.size}'
            if r.status != 206 or r.headers.get('Content-Range') != expected:
                raise ValueError(f'Server did not honor byte range: {r.status} {r.headers.get("Content-Range")}')
            data = r.read(end - start + 2)
        if len(data) != end - start + 1:
            raise ValueError('Truncated or oversized HTTP range')
        self.ranges.append(dict(start=start, end=end, sha256=hashlib.sha256(data).hexdigest()))
        return data

    def records(self, data, offset):
        pos = 0 if offset == 0 else data.find(b'\n') + 1
        if offset and pos == 0:
            return
        while pos < len(data):
            end = data.find(b'\n', pos)
            if end < 0:
                break
            line = data[pos:end].decode('utf-8-sig').rstrip('\r')
            values = next(csv.reader([line]))
            if len(values) == len(self.fields) and values[0] != self.fields[0]:
                yield offset + pos, dict(zip(self.fields, values))
            pos = end + 1

    def lower_bound(self, target):
        lo, hi = 0, self.size
        while hi - lo > 65536:
            mid = (lo + hi) // 2
            sample = next(self.records(self.block(mid, mid + 16383), mid), None)
            if sample is None:
                raise ValueError('Cannot locate complete CSV record')
            if self.key(sample[1]) < target:
                lo = mid
            else:
                hi = mid
        start = max(0, lo - 1024)
        for offset, row in self.records(self.block(start, min(self.size - 1, hi + 65536)), start):
            if self.key(row) >= target:
                return offset
        return self.size

    def between(self, lower, upper):
        start, end = self.lower_bound(lower), self.lower_bound(upper)
        # Read exact complete records; preserve line boundaries between chunks.
        carry = b''
        previous = None
        for offset in range(start, end, 4 * 1024 * 1024):
            data = carry + self.block(offset, min(end - 1, offset + 4 * 1024 * 1024 - 1))
            split = data.rfind(b'\n')
            complete, carry = data[:split + 1], data[split + 1:]
            for line in complete.decode('utf-8-sig').splitlines():
                row = dict(zip(self.fields, next(csv.reader([line]))))
                key = self.key(row)
                if previous is not None and key < previous:
                    raise ValueError('Archive sort order changed; cannot safely range-filter')
                previous = key
                if not lower <= key < upper:
                    raise ValueError(f'Out-of-bounds range extraction: {key!r}, bounds {lower!r}..{upper!r}, byte range {start}..{end}')
                yield row
        if carry:
            raise ValueError('Extraction ended inside a CSV record')


def extract_event(event, window, files):
    year = STORMS[event]['year']
    file = next(f for f in files if f['name'] == f'eaglei_outages_{year}.csv')
    start, end = (dt.strftime('%Y-%m-%d %H:%M:%S') for dt in window)
    # 2017/2019/2021 sorted by UTC timestamp; 2024 sorted by county, then time.
    cache = ROOT / 'data' / 'cache'
    cache.mkdir(parents=True, exist_ok=True)
    cached = cache / f'{event}_v4.json'
    if cached.exists():
        saved = json.loads(cached.read_text(encoding='utf-8'))
        if saved['evidence']['file'] == file and saved['evidence']['extraction_start_utc'] == start and saved['evidence']['extraction_end_utc_exclusive'] == end:
            print(f'{event}: reused validated extraction cache', flush=True)
            return saved['rows'], saved['evidence']
    if year == 2024:
        return extract_2024(event, window, file, cached)
    archive = RangeCSV(file, lambda r: r['run_start_time'])
    selected = []
    bounds = [(fips, str(int(fips) + 1).zfill(5)) for fips in sorted(COUNTIES)] if year == 2024 else [(start, end)]
    for lower, upper in bounds:
        for row in archive.between(lower, upper):
            if row['fips_code'] in COUNTIES and start <= row['run_start_time'] < end:
                selected.append(dict(fips_code=row['fips_code'], county=row['county'], state=row['state'],
                    customers_out=row['customers_out'], run_start_time=row['run_start_time'],
                    total_customers=row.get('total_customers', ''), storm_event=event,
                    source_file_id=file['id']))
    print(f'{event}: {len(selected):,} source records', flush=True)
    evidence = dict(event=event, file=file, http_ranges=archive.ranges,
                    extraction_start_utc=start, extraction_end_utc_exclusive=end,
                    method='UTC time-sorted archive byte-range subset; selected range monotonicity verified')
    write_json(cached, dict(rows=selected, evidence=evidence))
    return selected, evidence


def extract_2024(event, window, file, cached):
    """Scan every byte: the official 2024 CSV contains misplaced county rows."""
    start, end = (dt.strftime('%Y-%m-%d %H:%M:%S') for dt in window)
    chunk_size = 16 * 1024 * 1024
    prefixes = tuple((fips + ',').encode() for fips in COUNTIES)
    def chunk(offset):
        # Include one full-record overlap; process lines whose starting byte is in this chunk.
        low = max(0, offset - 1024)
        high = min(file['size'] - 1, offset + chunk_size + 1024 - 1)
        url = file['download_url'] + f'?range={low}-{high}'
        with get(url, {'Range': f'bytes={low}-{high}'}) as r:
            if r.status != 206 or r.headers.get('Content-Range') != f'bytes {low}-{high}/{file["size"]}':
                raise ValueError('Full-scan byte range not honored')
            data = r.read(high - low + 2)
        if len(data) != high - low + 1:
            raise ValueError('Truncated full-scan chunk')
        records = []
        pos = 0 if low == 0 else data.find(b'\n') + 1
        while pos < len(data):
            line_end = data.find(b'\n', pos)
            if line_end < 0:
                break
            absolute = low + pos
            if offset <= absolute < min(file['size'], offset + chunk_size):
                line = data[pos:line_end].rstrip(b'\r')
                if line.startswith(prefixes):
                    values = next(csv.reader([line.decode('utf-8')]))
                    fips, county, state, customers, stamp, total = values
                    if start <= stamp < end:
                        records.append(dict(fips_code=fips, county=county, state=state, customers_out=customers,
                            run_start_time=stamp, total_customers=total, storm_event=event, source_file_id=file['id']))
            pos = line_end + 1
        return records, dict(start=low, end=high, sha256=hashlib.sha256(data).hexdigest())
    rows, ranges = [], []
    offsets = list(range(0, file['size'], chunk_size))
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for n, (records, evidence) in enumerate(pool.map(chunk, offsets), 1):
            rows.extend(records)
            ranges.append(evidence)
            if n % 16 == 0:
                print(f'Beryl full-source scan: {n}/{len(offsets)} blocks', flush=True)
    evidence = dict(event=event, file=file, http_ranges=ranges,
        extraction_start_utc=start, extraction_end_utc_exclusive=end,
        method='full-file chunked scan; county sorting not assumed due to misplaced source rows')
    write_json(cached, dict(rows=rows, evidence=evidence))
    print(f'{event}: {len(rows):,} source records', flush=True)
    return rows, evidence


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    with get(ARTICLE) as r:
        metadata_bytes = r.read()
    (RAW / 'eaglei_release_v4.json').write_bytes(metadata_bytes)
    meta = json.loads(metadata_bytes)
    rows, extractions = [], []
    windows = weather_windows()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(extract_event, event, window, meta['files']) for event, window in windows.items()]
        for future in concurrent.futures.as_completed(futures):
            records, evidence = future.result()
            rows.extend(records)
            extractions.append(evidence)
    rows.sort(key=lambda r: (r['storm_event'], r['fips_code'], r['run_start_time']))
    write_csv(RAW / 'houston_power_outages_15min_eaglei.csv', rows)
    with get(CNP_URL) as r:
        html = r.read().decode('utf-8')
    (RAW / 'centerpoint_beryl_updates.html').write_bytes(html.encode('utf-8'))
    # Curate only achieved milestones explicitly present in the official index.
    write_csv(RAW / 'centerpoint_beryl_milestones.csv', centerpoint_milestones(html))
    write_json(RAW / 'retrieval_manifest.json', dict(retrieved_at_utc=utc_text(datetime.now(UTC)),
        archive_metadata_url=ARTICLE, archive_doi=meta['doi'], license=meta['license'],
        extractions=sorted(extractions, key=lambda r: r['event']), centerpoint_url=CNP_URL,
        absence_policy='Absent county-quarter-hours remain unknown, never imputed to zero.'))


if __name__ == '__main__':
    main()
