"""Validate the release and publish only the local server's public directories."""
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def build():
    subprocess.run([sys.executable, '-m', 'stormdata.validate'], cwd=ROOT, check=True)
    public = ROOT / 'public'
    for name in ('dashboard', 'data/processed', 'docs'):
        shutil.copytree(ROOT / name, public / name, dirs_exist_ok=True)


if __name__ == '__main__':
    build()
