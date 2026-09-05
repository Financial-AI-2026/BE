from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "raw"
INTERIM_DIR = ROOT / "interim"
OUT_DIR = ROOT / "out"
REPORTS_DIR = ROOT / "reports"


def ensure_output_dirs() -> None:
    for path in (RAW_DIR, INTERIM_DIR, OUT_DIR, REPORTS_DIR):
        path.mkdir(parents=True, exist_ok=True)

