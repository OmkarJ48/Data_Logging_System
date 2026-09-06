import os
import asyncio
import shutil
import tempfile
import json
import uuid
import ipaddress
import shlex
from dotenv import load_dotenv
from typing import List, Optional, Dict, Annotated, Set
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
import logging

from apps.central_hub.backend.config import RIG_IPS, RIG_TARGETS

router = APIRouter()
logger = logging.getLogger(__name__)

# Deployment IP whitelist from environment variable
load_dotenv() # Loads from .env in project root by default
DEPLOY_IP_WHITELIST: Set[str] = {
    ip.strip()
    for ip in os.getenv("DEPLOY_IP_WHITELIST", "127.0.0.1,::1").split(",")
    if ip.strip()
}
HUB_RIG_IDS: Set[str] = {"rnd_hub"}
RND_REPO_PATH = "/home/pi/RnD/"
RND_REPO_ORIGIN = os.getenv("RND_REPO_ORIGIN", "https://github.com/tlelean/RnD.git")
DEPLOY_SSH_KEY_PATH = "/home/pi/.ssh/deploy_rnd"
RND_REPO_SSH_KEY_PATH = os.getenv("RND_REPO_SSH_KEY_PATH", DEPLOY_SSH_KEY_PATH)
GIT_CREDENTIALS_PATH = "/root/.git-credentials"

# In-memory storage for active deployment sessions (temp_dir mapping)
active_sessions: Dict[str, str] = {}

# Store connected websocket clients for logs
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Failed to send websocket message: {e}")

manager = ConnectionManager()

def _is_ip_allowed(client_ip: str) -> bool:
    # Accept exact IP entries and CIDR ranges in DEPLOY_IP_WHITELIST.
    if not client_ip:
        return False

    try:
        parsed_ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return False

    for entry in DEPLOY_IP_WHITELIST:
        try:
            if "/" in entry:
                network = ipaddress.ip_network(entry, strict=False)
                if parsed_ip in network:
                    return True
            elif parsed_ip == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False

def _extract_client_ip(request: Request) -> str:
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()

    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        return x_real_ip.strip()

    return request.client.host if request.client else ""

def _extract_ws_client_ip(websocket: WebSocket) -> str:
    x_forwarded_for = websocket.headers.get("x-forwarded-for")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()

    x_real_ip = websocket.headers.get("x-real-ip")
    if x_real_ip:
        return x_real_ip.strip()

    return websocket.client.host if websocket.client else ""

def _enforce_whitelist(client_ip: str):
    if not _is_ip_allowed(client_ip):
        logger.warning(f"Deploy access denied for IP: {client_ip}")
        raise HTTPException(status_code=403, detail="Deploy access denied for this IP")

def is_request_ip_allowed(request: Request) -> bool:
    return _is_ip_allowed(_extract_client_ip(request))

def _is_hub_rig(rig_id: str) -> bool:
    return rig_id in HUB_RIG_IDS

def _build_git_update_payload() -> str:
    repo_path_q = shlex.quote(RND_REPO_PATH)
    origin_q = shlex.quote(RND_REPO_ORIGIN)
    repo_ssh_key_q = shlex.quote(RND_REPO_SSH_KEY_PATH)

    return (
        "set -e; "
        f"repo_path={repo_path_q}; "
        f"origin_url={origin_q}; "
        f"git_key={repo_ssh_key_q}; "
        "repo_user=$(stat -c '%U' \"$repo_path\"); "
        "repo_group=$(stat -c '%G' \"$repo_path\"); "
        "run_as_repo_owner() { "
        "if [ \"$(id -un)\" = \"$repo_user\" ]; then \"$@\"; "
        "elif command -v sudo >/dev/null 2>&1; then sudo -H -u \"$repo_user\" -- \"$@\"; "
        "elif command -v runuser >/dev/null 2>&1; then runuser -u \"$repo_user\" -- \"$@\"; "
        "else echo 'Cannot run git as repo owner: sudo/runuser not found' >&2; return 127; "
        "fi; "
        "}; "
        "state_dir=\"$repo_path/.deploy-state\"; "
        "dependency_marker=\"$state_dir/dependencies.changed\"; "
        "mkdir -p \"$state_dir\"; "
        "repo_git_key=\"\"; "
        "git_ssh_command=\"\"; "
        "case \"$origin_url\" in git@*|ssh://*) needs_git_ssh_key=1 ;; *) needs_git_ssh_key=0 ;; esac; "
        "if [ \"$needs_git_ssh_key\" = 1 ] && [ -f \"$git_key\" ]; then "
        "repo_git_key=\"$git_key\"; "
        "if ! run_as_repo_owner test -r \"$git_key\"; then "
        "repo_git_key=\"$state_dir/github_deploy_key\"; "
        "cp \"$git_key\" \"$repo_git_key\"; "
        "chown \"$repo_user\" \"$repo_git_key\"; "
        "chmod 600 \"$repo_git_key\"; "
        "fi; "
        "git_ssh_command=\"ssh -i $repo_git_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=no\"; "
        "fi; "
        "cd \"$repo_path\"; "
        "previous_head=$(run_as_repo_owner git rev-parse HEAD 2>/dev/null || true); "
        "if [ \"$needs_git_ssh_key\" = 1 ]; then "
        "run_as_repo_owner git remote set-url origin \"$origin_url\"; "
        "run_as_repo_owner env GIT_SSH_COMMAND=\"$git_ssh_command\" git fetch origin main; "
        "else "
        "git remote set-url origin \"$origin_url\"; "
        "git -c credential.helper=store fetch origin main; "
        "chown -R \"$repo_user:$repo_group\" .git; "
        "fi; "
        "run_as_repo_owner git reset --hard origin/main; "
        "run_as_repo_owner git clean -fd -e .deploy-state; "
        "current_head=$(run_as_repo_owner git rev-parse HEAD); "
        "mkdir -p \"$state_dir\"; "
        "if [ -n \"$previous_head\" ] && "
        "run_as_repo_owner git diff --quiet \"$previous_head\" \"$current_head\" -- "
        "requirements.txt apps/dls/deploy/sync_dependencies.sh; "
        "then printf '0\\n' > \"$dependency_marker\"; "
        "else printf '1\\n' > \"$dependency_marker\"; "
        "fi; "
        "chown \"$repo_user\" \"$state_dir\" \"$dependency_marker\""
    )

def _build_dependency_sync_payload() -> str:
    repo_path_q = shlex.quote(RND_REPO_PATH)
    service_name_q = shlex.quote("visualisation.service")
    return (
        f"cd {repo_path_q} && "
        "if [ -f apps/dls/deploy/sync_dependencies.sh ]; then "
        "chmod +x apps/dls/deploy/sync_dependencies.sh && "
        f"apps/dls/deploy/sync_dependencies.sh {repo_path_q} {service_name_q}; "
        "else "
        "apt-get update && apt-get install -y python3-numpy python3-opencv python3-picamera2 && "
        "python3 -m pip install --break-system-packages 'numpy<2' && "
        "grep -Eiv '^[[:space:]]*(numpy|opencv-python)([[:space:]=<>!~].*)?$' requirements.txt "
        "> /tmp/rnd-requirements-no-camera-abi.txt && "
        "python3 -m pip install --break-system-packages -r /tmp/rnd-requirements-no-camera-abi.txt && "
        "python3 -c 'import cv2; import picamera2'; "
        "fi"
    )

def _build_dependency_change_check_payload() -> str:
    repo_path_q = shlex.quote(RND_REPO_PATH)
    return (
        f"cd {repo_path_q} && "
        "dependency_marker=$(cat .deploy-state/dependencies.changed 2>/dev/null || printf 1); "
        "if [ \"$dependency_marker\" != 0 ] || [ ! -f .deploy-state/requirements.sha256 ]; then "
        "printf 1; "
        "else "
        "service_python=$(systemctl show visualisation.service -p ExecStart --value 2>/dev/null "
        "| grep -o 'path=[^ ;]*python[^ ;]*' | head -n1 | cut -d= -f2 || true); "
        "python_cmd=python3; "
        "if [ -n \"$service_python\" ] && [ -x \"$service_python\" ]; then python_cmd=\"$service_python\"; "
        "elif [ -x .venv/bin/python ]; then python_cmd=.venv/bin/python; fi; "
        "if \"$python_cmd\" -c 'import cv2; import picamera2' >/dev/null 2>&1; "
        "then printf 0; else printf 1; fi; "
        "fi"
    )

def _repo_origin_uses_https() -> bool:
    return RND_REPO_ORIGIN.startswith(("https://", "http://"))

@router.get("/api/deploy/access")
async def deploy_access(request: Request):
    client_ip = _extract_client_ip(request)
    return {"allowed": _is_ip_allowed(client_ip)}

@router.get("/api/deploy/rigs")
async def get_rig_targets(request: Request):
    client_ip = _extract_client_ip(request)
    _enforce_whitelist(client_ip)
    return {"rigs": RIG_TARGETS}

@router.post("/api/deploy/login")
async def login(request: Request):
    client_ip = _extract_client_ip(request)
    _enforce_whitelist(client_ip)
    return {"ok": True}

@router.websocket("/api/deploy/ws")
async def websocket_endpoint(websocket: WebSocket):
    client_ip = _extract_ws_client_ip(websocket)

    if not _is_ip_allowed(client_ip):
        logger.warning(f"WebSocket deploy access denied from {client_ip}")
        # To avoid 403 Forbidden handshake rejection, we accept then close with a code
        await websocket.accept()
        await websocket.send_text("ERROR: Deploy access denied for this IP.")
        await websocket.close(code=4003)
        return

    await manager.connect(websocket)
    logger.info(f"WebSocket connected from {client_ip}")
    try:
        while True:
            # Keep the connection open and handle incoming messages if any
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)

async def log_to_ws(message: str):
    logger.info(message)
    await manager.broadcast(message)

@router.post("/api/deploy/upload")
async def upload_files(
    request: Request,
    app_file: UploadFile = File(...),
    crc_file: UploadFile = File(...),
    visu_files: Optional[List[UploadFile]] = File(None),
    visu_paths: Optional[str] = Form(None) # JSON string list of relative paths
):
    client_ip = _extract_client_ip(request)
    _enforce_whitelist(client_ip)

    # Create a temporary directory to store uploaded files
    temp_dir = tempfile.mkdtemp(prefix="deploy_")
    session_id = str(uuid.uuid4())
    active_sessions[session_id] = temp_dir

    try:
        # Save files
        for file in [app_file, crc_file]:
            # Sanitize filename to prevent path traversal
            filename = os.path.basename(file.filename)
            file_path = os.path.join(temp_dir, filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

        if visu_files and visu_paths:
            paths = json.loads(visu_paths)
            if len(paths) != len(visu_files):
                raise ValueError("Mismatch between visu files and paths count")

            visu_base_dir = os.path.join(temp_dir, "visu")
            os.makedirs(visu_base_dir, exist_ok=True)

            for file, rel_path in zip(visu_files, paths):
                # rel_path typically looks like "visu/something.js"
                parts = rel_path.split("/")
                if len(parts) > 1:
                    actual_parts = parts[1:]
                else:
                    actual_parts = parts

                # Sanitize components to prevent traversal
                safe_parts = [os.path.basename(p) for p in actual_parts if p and p not in (".", "..")]
                dest_path = os.path.join(visu_base_dir, *safe_parts)

                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with open(dest_path, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)

        return {"session_id": session_id}
    except Exception as e:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        if session_id in active_sessions:
            del active_sessions[session_id]
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/deploy/run")
async def run_deploy(
    request: Request,
    session_id: Annotated[str, Form()],
    selected_rigs: Annotated[str, Form()]
):
    client_ip = _extract_client_ip(request)
    _enforce_whitelist(client_ip)

    temp_dir = active_sessions.get(session_id)
    if not temp_dir or not os.path.exists(temp_dir):
        raise HTTPException(status_code=400, detail="Invalid or expired session")

    try:
        rig_ids = json.loads(selected_rigs)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid rig selection format")

    # Start deployment in background
    # Remove from active_sessions so it can't be reused
    del active_sessions[session_id]
    asyncio.create_task(execute_deployment(temp_dir, rig_ids))

    return {"status": "started"}

@router.post("/api/deploy/git-pull")
async def run_git_pull(
    request: Request,
    selected_rigs: Annotated[str, Form()],
):
    client_ip = _extract_client_ip(request)
    _enforce_whitelist(client_ip)

    try:
        rig_ids = json.loads(selected_rigs)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid rig selection format")

    asyncio.create_task(execute_git_pull(rig_ids))
    return {"status": "started"}

async def execute_deployment(temp_dir: str, rig_ids: List[str]):
    try:
        await log_to_ws(">>> Starting deployment...")
        succeeded = 0
        failed = 0
        skipped = 0

        key_path = DEPLOY_SSH_KEY_PATH

        # Ensure .ssh directory exists (though the key itself might be missing)
        ssh_dir = os.path.dirname(key_path)
        if not os.path.exists(ssh_dir):
            try:
                os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
            except Exception as e:
                await log_to_ws(f"ERROR: Could not create SSH directory {ssh_dir}: {e}")
                return

        if not os.path.exists(key_path):
            await log_to_ws(f"ERROR: SSH key not found at {key_path}")
            await log_to_ws("Please ensure the key is placed on the server.")
            return

        # Find files in temp_dir
        app_files = [f for f in os.listdir(temp_dir) if f.endswith(".app")]
        crc_files = [f for f in os.listdir(temp_dir) if f.endswith(".crc")]

        visu_dir = os.path.join(temp_dir, "visu")

        if not app_files or not crc_files:
            await log_to_ws("ERROR: Missing required files (.app or .crc)")
            return

        app_file = os.path.join(temp_dir, app_files[0])
        crc_file = os.path.join(temp_dir, crc_files[0])

        for rig_id in rig_ids:
            if _is_hub_rig(rig_id):
                await log_to_ws(">>> Skipping CODESYS deployment for hub target (Git update only).")
                skipped += 1
                continue

            ip = RIG_IPS.get(rig_id)
            if not ip:
                await log_to_ws(f"ERROR: Unknown rig ID {rig_id}")
                failed += 1
                continue

            await log_to_ws(f"==> Deploying to {rig_id} ({ip})")

            # 1. Copy .app and .crc
            updates_path = "/var/opt/codesys/PlcLogic/DLS/Updates/"
            await log_to_ws(f"   -> Copying {app_files[0]} and {crc_files[0]}")
            await run_command([
                "ssh", "-i", key_path, "-o", "StrictHostKeyChecking=no",
                f"root@{ip}", f"mkdir -p {updates_path}"
            ])

            success = await run_command([
                "scp", "-i", key_path, "-o", "StrictHostKeyChecking=no", "-C", "-q",
                app_file, crc_file, f"root@{ip}:{updates_path}"
            ])
            if not success:
                await log_to_ws(f"FAILED to copy app/crc files to {rig_id}")
                failed += 1
                continue

            # 2. Copy visu if exists
            if os.path.exists(visu_dir):
                visu_remote_path = "/var/opt/codesys/PlcLogic/DLS/Updates/visu"
                await run_command([
                    "ssh", "-i", key_path, "-o", "StrictHostKeyChecking=no",
                    f"root@{ip}", f"mkdir -p {visu_remote_path}"
                ])

                await log_to_ws("   -> Copying visu contents")
                success = await run_command([
                    "scp", "-i", key_path, "-o", "StrictHostKeyChecking=no", "-r", "-C", "-q",
                    f"{visu_dir}/.", f"root@{ip}:{visu_remote_path}/"
                ])
                if not success:
                    await log_to_ws(f"FAILED to copy visu contents to {rig_id}")
                    failed += 1
                    continue

            await log_to_ws(f"==> Deployment complete for {rig_id}")
            succeeded += 1

        await log_to_ws(
            f">>> Deployment run finished: {succeeded} succeeded, {failed} failed, {skipped} skipped."
        )
    except Exception as e:
        await log_to_ws(f"CRITICAL ERROR during deployment: {str(e)}")
    finally:
        # Cleanup temp dir
        try:
            if os.path.exists(temp_dir) and "deploy_" in temp_dir:
                shutil.rmtree(temp_dir)
        except Exception as e:
            logger.error(f"Failed to cleanup temp dir: {e}")

async def execute_git_pull(rig_ids: List[str]):
    try:
        await log_to_ws(">>> Starting Git Update and dependency sync process...")
        succeeded = 0
        failed = 0

        key_path = DEPLOY_SSH_KEY_PATH
        if not os.path.exists(key_path):
            await log_to_ws(f"ERROR: SSH key not found at {key_path}")
            return

        for rig_id in rig_ids:
            ip = RIG_IPS.get(rig_id)
            if not ip:
                await log_to_ws(f"ERROR: Unknown rig ID {rig_id}")
                failed += 1
                continue

            git_payload = _build_git_update_payload()

            await log_to_ws(f"==> Updating Git repo on {rig_id} ({ip})")

            if _repo_origin_uses_https():
                await log_to_ws("   -> Syncing GitHub HTTPS credentials")
                credentials_success = await sync_git_credentials_to_target(
                    ip, key_path
                )
                if not credentials_success:
                    await log_to_ws(f"FAILED to sync GitHub credentials to {rig_id}")
                    failed += 1
                    continue

            # Execute git pull
            await log_to_ws("   -> Running git update as the existing repo directory owner")
            await log_to_ws(f"   -> Executing git update in {RND_REPO_PATH}")
            success = await run_command([
                "ssh", "-i", key_path, "-o", "StrictHostKeyChecking=no",
                f"root@{ip}", git_payload
            ])

            if success:
                await log_to_ws(f"Git update complete for {rig_id}")
                dependency_changed = await run_command_output([
                    "ssh", "-i", key_path, "-o", "StrictHostKeyChecking=no",
                    f"root@{ip}", _build_dependency_change_check_payload()
                ])
                if dependency_changed is None:
                    await log_to_ws(f"FAILED to check dependency changes on {rig_id}")
                    failed += 1
                    continue

                if dependency_changed.strip() != "0":
                    await log_to_ws("   -> Dependency sync needed; syncing Python dependencies")
                    dependency_success = await run_command([
                        "ssh", "-i", key_path, "-o", "StrictHostKeyChecking=no",
                        f"root@{ip}", _build_dependency_sync_payload()
                    ])
                    if not dependency_success:
                        await log_to_ws(f"FAILED to sync Python dependencies on {rig_id}")
                        failed += 1
                        continue
                else:
                    await log_to_ws("   -> Dependencies already current; skipping Python dependency sync")

                await log_to_ws("   -> Restarting visualisation.service")
                restart_success = await run_command([
                    "ssh", "-i", key_path, "-o", "StrictHostKeyChecking=no",
                    f"root@{ip}", "sudo systemctl restart visualisation.service"
                ])
                if restart_success:
                    await log_to_ws(f"visualisation.service restarted on {rig_id}")
                    succeeded += 1
                else:
                    await log_to_ws(f"FAILED to restart visualisation.service on {rig_id}")
                    failed += 1
            else:
                await log_to_ws(f"FAILED to update Git repo on {rig_id}")
                failed += 1

        await log_to_ws(f">>> Git update and dependency sync run finished: {succeeded} succeeded, {failed} failed.")
    except Exception as e:
        await log_to_ws(f"CRITICAL ERROR during Git update: {str(e)}")

async def sync_git_credentials_to_target(ip: str, key_path: str) -> bool:
    if not await run_command(["sudo", "test", "-r", GIT_CREDENTIALS_PATH]):
        await log_to_ws(f"      ERROR: Git credentials not readable at {GIT_CREDENTIALS_PATH}")
        return False

    copied = await run_command([
        "sudo", "scp", "-i", key_path, "-o", "StrictHostKeyChecking=no",
        "-C", "-q", GIT_CREDENTIALS_PATH, f"root@{ip}:{GIT_CREDENTIALS_PATH}"
    ])
    if not copied:
        return False

    return await run_command([
        "ssh", "-i", key_path, "-o", "StrictHostKeyChecking=no",
        f"root@{ip}", f"chmod 600 {shlex.quote(GIT_CREDENTIALS_PATH)}"
    ])

async def run_command(cmd: List[str]) -> bool:
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _stdout, stderr = await process.communicate()

        if process.returncode != 0:
            if stderr:
                await log_to_ws(f"      ERROR: {stderr.decode().strip()}")
            return False
        return True
    except Exception as e:
        await log_to_ws(f"      EXECUTION ERROR: {str(e)}")
        return False

async def run_command_output(cmd: List[str]) -> Optional[str]:
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            if stderr:
                await log_to_ws(f"      ERROR: {stderr.decode().strip()}")
            return None
        return stdout.decode().strip()
    except Exception as e:
        await log_to_ws(f"      EXECUTION ERROR: {str(e)}")
        return None
