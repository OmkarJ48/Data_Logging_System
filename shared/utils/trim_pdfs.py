#!/usr/bin/env python3
import os
from pathlib import Path
import sys
import traceback

# Add project root to sys.path to ensure we can import the central config
root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.append(str(root))

from shared_config import PDF_DIR

# Max number of PDFs to keep
MAX_PDFS = 100

def trim_pdfs():
    try:
        if not PDF_DIR.exists():
            print(f"[WARN] PDF directory does not exist: {PDF_DIR}")
            return

        # Collect all PDF files
        pdfs = [
            p for p in PDF_DIR.glob("*.pdf")
            if p.is_file()
        ]

        # Nothing to trim
        if len(pdfs) <= MAX_PDFS:
            print(f"[OK] {len(pdfs)} PDFs present — no trimming required.")
            return

        # Sort oldest → newest by modification time
        pdfs.sort(key=lambda p: p.stat().st_mtime)

        # Determine how many need removal
        to_delete = pdfs[:-MAX_PDFS]

        print(f"[INFO] Trimming {len(to_delete)} old PDFs from: {PDF_DIR}")

        for f in to_delete:
            try:
                f.unlink()
                print(f"  [DEL] {f.name}")
            except Exception as e:
                print(f"  [ERR] Failed to delete {f.name}: {e}")

        print("[DONE] Trim complete.")

    except Exception as e:
        print(f"[FATAL] Unexpected error:\n{traceback.format_exc()}")


if __name__ == "__main__":
    trim_pdfs()
