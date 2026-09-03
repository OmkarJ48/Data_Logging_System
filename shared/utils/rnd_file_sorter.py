import argparse
import ctypes
import json
import logging
import os
import platform
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional


# -----------------------------
# Config
# -----------------------------

ROOT = Path("/mnt/rnddls")
INCOMING_ROOT = ROOT / "Incoming"

INVALID_WIN_CHARS = r'<>:"/\|?*'


# -----------------------------
# Logging (circular file capped at 500 MiB by deleting oldest lines)
# -----------------------------

LOG_FILE = INCOMING_ROOT / "rnd_file_sorter.log"
LOG_MAX_BYTES = 500 * 1024 * 1024


def hide_file(path: Path) -> None:
    """Hide a file on Windows; no-op elsewhere."""
    try:
        if platform.system() == "Windows":
            file_attribute_hidden = 0x02
            ctypes.windll.kernel32.SetFileAttributesW(str(path), file_attribute_hidden)
    except Exception:
        logging.getLogger(__name__).exception("Failed to hide log file: %s", path)


class TailKeepingFileHandler(logging.Handler):
    """Keep appending to a log file and trim old lines when it grows too large."""

    def __init__(self, filename: str, max_bytes: int, keep_ratio: float = 0.9, encoding: str = "utf-8"):
        super().__init__()
        self.filename = filename
        self.max_bytes = int(max_bytes)
        self.keep_ratio = float(keep_ratio)
        self.encoding = encoding
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            with self._lock:
                with open(self.filename, "a", encoding=self.encoding, errors="replace") as f:
                    f.write(msg + "\n")
                self._trim_if_needed()
        except Exception:
            self.handleError(record)

    def _trim_if_needed(self) -> None:
        try:
            size = os.path.getsize(self.filename)
        except FileNotFoundError:
            return

        if size <= self.max_bytes:
            return

        keep_bytes = int(self.max_bytes * self.keep_ratio)
        keep_bytes = max(1, min(keep_bytes, self.max_bytes))
        tmp_path = self.filename + ".tmp"

        with open(self.filename, "rb") as src_f, open(tmp_path, "wb") as dst_f:
            start = max(0, size - keep_bytes)
            src_f.seek(start)

            if start > 0:
                src_f.readline()

            while True:
                chunk = src_f.read(1024 * 1024)
                if not chunk:
                    break
                dst_f.write(chunk)

        os.replace(tmp_path, self.filename)


class _StreamToLogger:
    """Redirect writes from stdout/stderr to the logger."""

    def __init__(self, logger: logging.Logger, level: int):
        self.logger = logger
        self.level = level
        self._buffer = ""

    def write(self, message: str) -> int:
        if not message:
            return 0
        self._buffer += message
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.rstrip()
            if line:
                self.logger.log(self.level, line)
        return len(message)

    def flush(self) -> None:
        line = self._buffer.strip()
        if line:
            self.logger.log(self.level, line)
        self._buffer = ""


def setup_logging() -> None:
    """Console + capped file logging, plus capture print() output."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)

    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not LOG_FILE.exists():
            LOG_FILE.touch()
        hide_file(LOG_FILE)

        fh = TailKeepingFileHandler(
            filename=str(LOG_FILE),
            max_bytes=LOG_MAX_BYTES,
            keep_ratio=0.9,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:
        root.exception("Failed to set up file logging: %s", LOG_FILE)

    sys.stdout = _StreamToLogger(logging.getLogger("STDOUT"), logging.INFO)
    sys.stderr = _StreamToLogger(logging.getLogger("STDERR"), logging.ERROR)


# -----------------------------
# Helpers
# -----------------------------

def safe_part(text: Optional[str], fallback: str) -> str:
    """Make a safe folder name for Windows and avoid empty parts."""
    value = "".join(ch for ch in str(text or "") if ch >= " ").strip()
    if not value:
        return fallback
    cleaned = "".join("_" if c in INVALID_WIN_CHARS else c for c in value).strip()
    return cleaned or fallback


def normalise_attempt(value: Optional[str]) -> str:
    text = str(value or "").strip()
    if not text:
        return "1"
    try:
        attempt = int(text)
    except Exception:
        return "1"
    return str(attempt) if attempt > 0 else "1"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def wait_until_stable(path: Path, stable_for_s: float = 2.0, timeout_s: float = 60.0) -> bool:
    """Wait until a file stops changing (size/mtime) to avoid reading half-written files."""
    start = time.time()
    last = None
    stable_since = None

    while time.time() - start < timeout_s:
        if not path.exists():
            stable_since = None
            time.sleep(0.25)
            continue

        stat = path.stat()
        current = (stat.st_size, stat.st_mtime)

        if current == last:
            if stable_since is None:
                stable_since = time.time()
            if time.time() - stable_since >= stable_for_s:
                return True
        else:
            stable_since = None
            last = current

        time.sleep(0.25)

    return False


def wait_for_files(paths: List[Path], stable_for_s: float = 2.0, timeout_s: float = 120.0) -> bool:
    """Wait for each file in the list to become stable."""
    for path in paths:
        if not wait_until_stable(path, stable_for_s=stable_for_s, timeout_s=timeout_s):
            logging.warning("File not stable yet: %s", path)
            return False
    return True


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def find_details_file(run_dir: Path) -> Optional[Path]:
    """Prefer <run_id>_details.json, then any *_details.json, then details.json."""
    specific = run_dir / f"{run_dir.name}_details.json"
    if specific.exists():
        return specific

    candidates = sorted(run_dir.glob("*_details.json"))
    if candidates:
        return candidates[0]

    fallback = run_dir / "details.json"
    if fallback.exists():
        return fallback

    return None


def status_markers(run_dir: Path) -> List[Path]:
    markers = []
    for name in ("status.pass", "status.fail"):
        path = run_dir / name
        if path.exists():
            markers.append(path)
    return markers


def decision_from_status_files(run_dir: Path) -> Optional[str]:
    """Return 'pass', 'fail', or None based on status marker files."""
    pass_marker = run_dir / "status.pass"
    fail_marker = run_dir / "status.fail"

    has_pass = pass_marker.exists()
    has_fail = fail_marker.exists()

    if has_pass and has_fail:
        logging.warning("Both status.pass and status.fail exist in %s; treating as FAIL", run_dir)
        return "fail"
    if has_pass:
        return "pass"
    if has_fail:
        return "fail"
    return None


def build_destinations(details: dict) -> Dict[str, Path]:
    meta = details.get("metadata", details)

    operator = safe_part(meta.get("Operator"), "Unknown")
    job_number = safe_part(meta.get("Job Number"), "Unknown")
    valve = safe_part(meta.get("Valve Drawing Number"), "Unknown")
    attempt = normalise_attempt(meta.get("Attempt"))
    section = safe_part(meta.get("Test Section Number"), "Unknown")

    base_attempt = ROOT / operator / job_number / valve / f"Attempt {attempt}"

    return {
        "csv_pass": base_attempt / "CSV" / section,
        "pdf_pass": base_attempt / "PDF",
        "fail_all": base_attempt / "Failed" / section,
    }


def safe_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def safe_move(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        if dst.is_file() or dst.is_symlink():
            dst.unlink()
        else:
            shutil.rmtree(dst)
    shutil.move(str(src), str(dst))


# -----------------------------
# Core processing
# -----------------------------

def cleanup_run_folder(run_dir: Path, data_csvs: List[Path], details_path: Path, marker_paths: List[Path]) -> None:
    """Delete source files and the run folder if empty."""
    for csv_path in data_csvs:
        try:
            csv_path.unlink()
        except FileNotFoundError:
            pass
        except Exception as e:
            logging.warning("Could not delete %s: %s", csv_path, e)

    try:
        details_path.unlink()
    except FileNotFoundError:
        pass
    except Exception as e:
        logging.warning("Could not delete %s: %s", details_path, e)

    for marker_path in marker_paths:
        try:
            marker_path.unlink()
        except FileNotFoundError:
            pass
        except Exception as e:
            logging.warning("Could not delete %s: %s", marker_path, e)

    try:
        next(run_dir.iterdir())
        logging.info("Run folder not empty (leftovers kept): %s", run_dir)
    except StopIteration:
        run_dir.rmdir()
        logging.info("Processed and removed run folder: %s", run_dir)


def process_run_folder(run_dir: Path, dry_run: bool = False) -> None:
    """Process one run folder inside Incoming."""
    if not run_dir.is_dir():
        return

    decision = decision_from_status_files(run_dir)
    if decision is None:
        return

    with _processing_lock:
        if str(run_dir) in _processing_folders:
            return
        _processing_folders.add(str(run_dir))

    try:
        marker_paths = status_markers(run_dir)
        if not wait_for_files(marker_paths):
            return

        decision = decision_from_status_files(run_dir)
        if decision is None:
            return
        marker_paths = status_markers(run_dir)

        details_path = find_details_file(run_dir)
        if not details_path:
            logging.warning("No details.json / *_details.json found in %s", run_dir)
            return

        data_csvs = sorted(run_dir.glob("*.csv"))
        if not data_csvs:
            logging.warning("No CSV files found in %s", run_dir)
            return

        pdfs = sorted(run_dir.glob("*.pdf"))
        if not wait_for_files([details_path] + data_csvs + pdfs):
            return

        details = load_json(details_path)
        dests = build_destinations(details)

        if decision == "pass":
            dest_data_dir = dests["csv_pass"]
            dest_pdf_dir = dests["pdf_pass"]

            if dry_run:
                logging.info("[DRY] PASS data destination: %s", dest_data_dir)
                logging.info("[DRY] PASS pdf destination: %s", dest_pdf_dir)
            else:
                ensure_dir(dest_data_dir)
                ensure_dir(dest_pdf_dir)

            for csv_path in data_csvs:
                target_csv = dest_data_dir / csv_path.name
                if dry_run:
                    logging.info("[DRY] Copy %s -> %s", csv_path, target_csv)
                else:
                    safe_copy(csv_path, target_csv)

            target_details = dest_data_dir / details_path.name
            if dry_run:
                logging.info("[DRY] Copy %s -> %s", details_path, target_details)
            else:
                safe_copy(details_path, target_details)

            for pdf_path in pdfs:
                dest_pdf_path = dest_pdf_dir / pdf_path.name
                if dry_run:
                    logging.info("[DRY] Move %s -> %s", pdf_path, dest_pdf_path)
                else:
                    safe_move(pdf_path, dest_pdf_path)

        else:
            fail_dest = dests["fail_all"]

            if dry_run:
                logging.info("[DRY] FAIL destination: %s", fail_dest)
            else:
                ensure_dir(fail_dest)

            for csv_path in data_csvs:
                target_csv = fail_dest / csv_path.name
                if dry_run:
                    logging.info("[DRY] Copy %s -> %s", csv_path, target_csv)
                else:
                    safe_copy(csv_path, target_csv)

            target_details = fail_dest / details_path.name
            if dry_run:
                logging.info("[DRY] Copy %s -> %s", details_path, target_details)
            else:
                safe_copy(details_path, target_details)

            for pdf_path in pdfs:
                dest_pdf_path = fail_dest / pdf_path.name
                if dry_run:
                    logging.info("[DRY] Move %s -> %s", pdf_path, dest_pdf_path)
                else:
                    safe_move(pdf_path, dest_pdf_path)

        if dry_run:
            logging.info("[DRY] Cleanup would delete inputs in %s", run_dir)
        else:
            cleanup_run_folder(run_dir, data_csvs, details_path, marker_paths)

    except Exception:
        logging.exception("Failed processing folder: %s", run_dir)
    finally:
        with _processing_lock:
            _processing_folders.discard(str(run_dir))


_processing_lock = threading.Lock()
_processing_folders = set()


def scan_existing(dry_run: bool = False) -> None:
    """On startup, process anything already sitting in Incoming."""
    if not INCOMING_ROOT.exists():
        logging.error("Incoming root does not exist: %s", INCOMING_ROOT)
        return

    for child in INCOMING_ROOT.iterdir():
        if child.is_dir():
            process_run_folder(child, dry_run=dry_run)


def run_poll_loop(poll_interval: float, dry_run: bool = False) -> None:
    """Poll Incoming repeatedly, which is the most reliable choice for Samba/CIFS mounts."""
    logging.info("Watching for new run folders using polling every %.1f seconds... (Ctrl+C to stop)", poll_interval)
    try:
        while True:
            scan_existing(dry_run=dry_run)
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        logging.info("Stopping watcher...")


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch Incoming folder and route RnD DLS files")
    parser.add_argument("--dry-run", action="store_true", help="Log actions without changing files")
    parser.add_argument("--poll", type=float, default=2.0, help="Polling interval in seconds (default: 2.0)")
    args = parser.parse_args()

    setup_logging()

    logging.info("Incoming: %s", INCOMING_ROOT)
    logging.info("Dest root: %s", ROOT)
    logging.info("Dry-run: %s", args.dry_run)

    scan_existing(dry_run=args.dry_run)
    run_poll_loop(args.poll, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
