from pathlib import Path

MONOREPO_ROOT = Path(__file__).resolve().parent.parent

HISTORICAL_CSV = MONOREPO_ROOT / "shared/static/historical.csv"
PDF_DIR = MONOREPO_ROOT / "shared/static/pdfs"
