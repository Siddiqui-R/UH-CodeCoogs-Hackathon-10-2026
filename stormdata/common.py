import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ZoneInfo('America/Chicago')
UTC = timezone.utc
COUNTIES = {'48201': 'Harris', '48157': 'Fort Bend', '48339': 'Montgomery',
            '48039': 'Brazoria', '48167': 'Galveston'}
STORMS = {
    'Hurricane_Harvey_2017': dict(name='Harvey', year=2017, sid='2017228N14314',
        claim_label='Hurricane Harvey', claim_start='2017-08-24', claim_end='2017-09-13'),
    'Tropical_Storm_Imelda_2019': dict(name='Imelda', year=2019, sid='2019261N28264',
        claim_label='Tropical Storm Imelda', claim_start='2019-09-17', claim_end='2019-09-24'),
    'Hurricane_Nicholas_2021': dict(name='Nicholas', year=2021, sid='2021256N21265',
        claim_label='Tropical Storm Nicholas', claim_start='2021-09-13', claim_end='2021-09-16'),
    'Hurricane_Beryl_2024': dict(name='Beryl', year=2024, sid='2024181N09320',
        claim_label='Hurricane Beryl', claim_start='2024-07-07', claim_end='2024-07-09'),
}


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc_text(dt):
    return dt.astimezone(UTC).isoformat(timespec='seconds').replace('+00:00', 'Z')


def weather_time(s):
    return datetime.fromisoformat(s).replace(tzinfo=LOCAL).astimezone(UTC)


def number(s):
    if s is None or not str(s).strip():
        return None
    value = float(s)
    import math
    if not math.isfinite(value):
        raise ValueError(f'Non-finite numeric value: {s}')
    return value


def weather_windows(root=ROOT):
    from datetime import timedelta
    rows = read_csv(root / 'houston_major_storms_hourly_weather.csv')
    return {ev: (min(weather_time(r['time']) for r in rows if r['storm_event'] == ev),
                 max(weather_time(r['time']) for r in rows if r['storm_event'] == ev) + timedelta(hours=1))
            for ev in STORMS}
