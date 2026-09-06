from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import List
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..config import MONOREPO_ROOT, PDF_DIR

router = APIRouter()


def read_when_unlocked(path: Path, timeout: float = 6.0, poll: float = 0.1) -> bytes:
    """
    Wait for Windows file locks to clear and return stable bytes.
    """
    deadline = time.time() + timeout
    last_size = -1
    while time.time() < deadline:
        try:
            size = os.path.getsize(path)
            if size != last_size:
                last_size = size
                time.sleep(poll)
                continue
            with open(path, "rb") as handle:
                return handle.read()
        except (PermissionError, OSError):
            time.sleep(poll)
    raise RuntimeError(f"File still locked after {timeout:.1f}s: {path}")


def unique_destination(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    counter = 1
    while True:
        candidate = path.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def persist_generated_pdfs(pdf_paths: List[Path]) -> list[dict[str, str]]:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    persisted_files: list[dict[str, str]] = []

    for pdf_path in sorted(pdf_paths, key=lambda p: (p.stat().st_mtime, p.name)):
        try:
            pdf_bytes = read_when_unlocked(pdf_path, timeout=6.0, poll=0.1)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"PDF was produced but is temporarily locked: {pdf_path.name}. Please retry.",
            ) from exc

        target_path = unique_destination(PDF_DIR / pdf_path.name)
        with open(target_path, "wb") as handle:
            handle.write(pdf_bytes)

        persisted_files.append(
            {
                "name": target_path.name,
                "download_url": f"/api/pdf/{quote(target_path.name)}",
            }
        )

    return persisted_files


@router.get("/api/pdf-list")
async def pdf_list() -> list[str]:
    try:
        if not PDF_DIR.is_dir():
            return []
        files = [f.name for f in PDF_DIR.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"]
        files.sort()
        return files
    except Exception:
        return []


@router.get("/api/pdf/{filename}")
async def get_pdf(filename: str):
    file_path = (PDF_DIR / filename).resolve()
    pdf_dir = PDF_DIR.resolve()

    if pdf_dir not in file_path.parents and file_path != pdf_dir:
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not file_path.is_file() or file_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(path=str(file_path), media_type="application/pdf", filename=file_path.name)


@router.post("/api/generate-pdf")
async def run_pdf_generation(
    data_csv: List[UploadFile] = File(...),
    details_json: UploadFile = File(...),
):
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            details_path = tmp / "details.json"
            out_dir = tmp / f"out_{int(time.time() * 1000)}"
            out_dir.mkdir(parents=True, exist_ok=True)

            with open(details_path, "wb") as handle:
                handle.write(await details_json.read())

            csv_paths = []
            for csv_file in data_csv:
                if not csv_file.filename:
                    continue
                target_path = tmp / csv_file.filename
                with open(target_path, "wb") as handle:
                    handle.write(await csv_file.read())
                csv_paths.append(target_path)

            if not csv_paths:
                raise HTTPException(status_code=400, detail="No valid data_csv files provided")

            csv_paths.sort(key=lambda p: p.name)
            before = {p.name for p in out_dir.glob("*.pdf")}

            chart_main = MONOREPO_ROOT / "shared" / "chart_generation" / "main.py"
            cmd = [sys.executable, str(chart_main), "--no-gui-output"]
            cmd.extend([str(path) for path in csv_paths])
            cmd.extend([str(details_path), str(out_dir)])

            env = os.environ.copy()
            env["PYTHONPATH"] = f"{MONOREPO_ROOT}:{env.get('PYTHONPATH', '')}"
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
            if proc.returncode != 0:
                raise HTTPException(
                    status_code=500,
                    detail=f"Generator failed ({proc.returncode}).\n{proc.stderr}",
                )

            time.sleep(0.05)
            created = [p for p in out_dir.glob("*.pdf") if p.name not in before]
            if not created:
                created = list(out_dir.glob("*.pdf"))
            if not created:
                raise HTTPException(status_code=500, detail="No PDF produced by generator.")

            persisted_files = persist_generated_pdfs(created)
            return {
                "ok": True,
                "files": persisted_files,
            }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Internal error: {exc}\n{traceback.format_exc()}") from exc
