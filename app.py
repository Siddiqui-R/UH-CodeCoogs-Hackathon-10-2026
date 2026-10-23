"""Local Houston storm evidence app. Run: python app.py"""
import argparse
import csv
import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parent


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def load_summary(root):
    with (root / 'data/processed/county_storm.csv').open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


class IntegrityCheck:
    """Recheck on file changes or explicit refresh; never run a write/build command."""
    def __init__(self, root=ROOT):
        self.root = root
        self.lock = threading.Lock()
        self.signature = None
        self.result = None

    def check(self, force=False):
        with self.lock:
            candidates = list((self.root / 'data/processed').glob('*'))
            candidates += list((self.root / 'data/raw').glob('*'))
            candidates += list((self.root / 'stormdata').glob('*.py'))
            candidates += list(self.root.glob('*.csv')) + list(self.root.glob('*.geojson')) + list(self.root.glob('*.zip'))
            signature = tuple((str(p), p.stat().st_size, p.stat().st_mtime_ns)
                              for p in sorted(candidates) if p.is_file())
            if self.result is not None and signature == self.signature and not force:
                return self.result
            try:
                run = subprocess.run([sys.executable, '-m', 'stormdata.validate'], cwd=self.root,
                    capture_output=True, text=True, timeout=30)
                passed = run.returncode == 0
                detail = run.stdout.strip() if passed else (run.stderr.strip().splitlines()[-1] if run.stderr.strip() else 'Validation did not complete.')
            except (OSError, subprocess.TimeoutExpired):
                passed, detail = False, 'Validation could not finish. Check the local Python setup and data files.'
            self.result = dict(passed=passed, checked_at_utc=datetime.now(timezone.utc).isoformat(), detail=detail,
                meaning='Covers processing, keys, time alignment and file fingerprints.')
            self.signature = signature
            return self.result


def describe_selection(row):
    observed = int(row['outage_observed_quarters'])
    expected = int(row['outage_expected_quarters'])
    missing = expected - observed
    state = 'complete' if observed == expected else 'missing' if observed == 0 else 'partial'
    return dict(county_fips=row['county_fips'], county_name=row['county_name'], storm_event=row['storm_event'],
        outage_state=state, usable_outage_quarters=observed, expected_outage_quarters=expected,
        missing_outage_quarters=missing, usable_outage_percent=round(100 * observed / expected, 1),
        weather_hours=int(row['weather_hours']), claim_count=int(row['nfip_recorded_claims']),
        missing_payment_component_claims=int(row['nfip_payment_missing_component_claims']),
        window_start_utc=row['window_start_utc'], window_end_utc_exclusive=row['window_end_utc_exclusive'],
        claim_start=row['nfip_claim_window_start'], claim_end=row['nfip_claim_window_end'])


def next_data(goal, selection):
    common = [
        dict(priority='Source verification', name='Original starter-file download metadata',
             fields='Provider dataset version, API request, retrieval date, units, and original response.',
             benefit='Verify the organizer-supplied weather, tracks, and claims against their upstream sources.'),
        dict(priority='CenterPoint detail', name='Historical CenterPoint county-level records',
             fields='County FIPS or documented service-area geometry, actual measurement time, customers out, customers served, and revision status.',
             benefit='Study CenterPoint directly at matching geography while keeping county totals from other utilities separate.'),
    ]
    recovery = dict(priority='Outage coverage', name='Outage snapshots through full recovery',
        fields='15-minute observations with explicit zeros, reporting coverage, outage start/end times, and documented gaps.',
        benefit=f'Fill {selection["missing_outage_quarters"]:,} unknown quarter-hours in this selection and extend beyond its current window.' if selection['missing_outage_quarters'] else 'Extend past the current window to measure full recovery.')
    if goal == 'forecasting':
        return [dict(priority='Required for prediction', name='More independent storms with reliable outage labels',
            fields='Consistent county-level outcomes, customer denominators, event IDs, and documented reporting coverage.',
            benefit='Test the model on whole storms it has never seen.'),
            dict(priority='Required for prediction', name='Archived forecasts issued before each storm',
            fields='Forecast issue time, valid time, forecast wind/rainfall/track, location, and forecast horizon.',
            benefit='Train on what forecasters knew before landfall, so the model works on the next storm.'), recovery, *common]
    if goal == 'preparedness':
        return [dict(priority='Required for prioritization', name='Population and social vulnerability',
            fields='County or tract IDs, population, age/disability/vehicle-access indicators, reference year, and geographic crosswalks.',
            benefit='Distinguish the number of people needing support from absolute outage counts.'),
            dict(priority='Required for prioritization', name='Critical facilities and backup-power capacity',
            fields='Hospitals, shelters, cooling centers, service areas, operating status, generator capacity, and last verified dates.',
            benefit='Connect documented disruption to the places that need generators, crews and cooling first.'), recovery, *common]
    return [recovery, *common, dict(priority='Weather detail', name='Additional weather stations or a spatial grid',
        fields='Coordinates, timestamps, units, sensor/reanalysis source, and quality flags.',
        benefit='Check how well the single weather reference point represents each county.')]


def readiness(root, storm, county, goal, integrity):
    report = load_json(root / 'data/processed/validation_report.json')
    summary = load_summary(root)
    row = next((r for r in summary if r['storm_event'] == storm and r['county_fips'] == county), None)
    if row is None:
        raise ValueError('Choose a storm and county present in the dataset.')
    if goal not in {'history', 'forecasting', 'preparedness'}:
        raise ValueError('Unknown analysis goal.')
    selection = describe_selection(row)
    overview = dict(hourly_rows=report['hourly_rows'], county_storm_rows=len(summary),
        independent_storms=report['independent_storms'], assigned_claims=report['assigned_claims'],
        missing_outage_quarters=report['missing_outage_quarters'], blank_outage_count_rows=report['blank_outage_count_rows'])
    if not integrity['passed']:
        verdict = 'File checks failed. Resolve the validation issue before relying on these results.'
    elif goal == 'forecasting':
        verdict = 'Ready to build outage-prediction features from four storms; archived forecasts and more storms will turn them into a tested model.'
    elif goal == 'preparedness':
        verdict = 'Ready to show where past storms hit hardest; adding population and facility data turns this into resource priorities.'
    else:
        verdict = 'Ready for historical comparison across four storms and five counties.'
    return dict(integrity=integrity, overview=overview, selection=selection, goal=goal, verdict=verdict,
        checks=report['checks'], warnings=report['warnings'], next_data=next_data(goal, selection),
        evidence_links=[dict(label='Validation report', url='/data/processed/validation_report.json'),
            dict(label='Source fingerprints', url='/data/processed/source_manifest.json'),
            dict(label='Claim assignment audit', url='/data/processed/claim_assignments.csv'),
            dict(label='Methodology', url='/docs/METHODOLOGY.md')])


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, root=ROOT, integrity=None, **kwargs):
        self.root = root.resolve()
        self.integrity = integrity
        super().__init__(*args, directory=str(root), **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        super().end_headers()

    def send_json(self, value, status=200):
        data = json.dumps(value, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == '/':
            self.send_response(302)
            self.send_header('Location', '/dashboard/')
            self.end_headers()
            return
        if url.path == '/api/readiness':
            query = parse_qs(url.query)
            try:
                check = self.integrity.check(force=query.get('refresh', ['0'])[0] == '1')
                data = readiness(self.root, query.get('storm', ['Hurricane_Beryl_2024'])[0],
                    query.get('county', ['48201'])[0], query.get('goal', ['history'])[0], check)
                self.send_json(data)
            except ValueError as exc:
                self.send_json(dict(error=str(exc)), 400)
            except (OSError, KeyError, StopIteration):
                self.send_json(dict(error='Required dataset files are unavailable. Run python -m stormdata.build and inspect validation.'), 503)
            return
        super().do_GET()

    def send_head(self):
        # Serve only the application, generated downloads, and its documentation.
        path = Path(self.translate_path(self.path)).resolve()
        allowed = [self.root / 'dashboard', self.root / 'data/processed', self.root / 'docs']
        if not any(path.is_relative_to(p) for p in allowed) or path.name.startswith('.'):
            self.send_error(404)
            return None
        if path.is_dir() and not (path / 'index.html').is_file():
            self.send_error(404)
            return None
        return super().send_head()


def create_server(port=8000, root=ROOT, integrity=None):
    check = integrity or IntegrityCheck(root)
    return ThreadingHTTPServer(('127.0.0.1', port), partial(Handler, root=root, integrity=check))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run the local Houston storm evidence app.')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    try:
        server = create_server(args.port)
    except OSError as exc:
        parser.exit(1, f'Cannot start the local app: {exc}\nTry python app.py --port 8001\n')
    print(f'Houston Storm Evidence: http://127.0.0.1:{server.server_port}/', flush=True)
    print('Local files only. Press Ctrl+C to stop.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
