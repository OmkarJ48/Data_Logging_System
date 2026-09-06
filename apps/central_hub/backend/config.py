from pathlib import Path

MONOREPO_ROOT = Path(__file__).resolve().parents[3]
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
ASSETS_DIR = FRONTEND_DIR / "assets"
SHARED_FRONTEND_ASSETS_DIR = MONOREPO_ROOT / "shared" / "frontend_assets"
STYLES_DIR = SHARED_FRONTEND_ASSETS_DIR
PAGES_DIR = FRONTEND_DIR / "pages"
HUB_HISTORICAL_TREND_PAGE = PAGES_DIR / "historical_trend.html"
SHARED_FRONTEND_PAGES_DIR = MONOREPO_ROOT / "shared" / "frontend_pages"
SHARED_HISTORICAL_TREND_PAGE = SHARED_FRONTEND_PAGES_DIR / "historical_trend.html"
PDF_DIR = MONOREPO_ROOT / "shared" / "static" / "pdfs"
STATIC_DIR = MONOREPO_ROOT / "shared" / "static"

# If someone browses the old portal host on kiosk, redirect here.
WEBVISU_URL = "http://127.0.0.1:8080/webvisu.htm"

# Deploy targets aligned to Rig Overview markers plus the R&D Hub host.
RIG_TARGETS = [
    {"id": "rnd_hub", "label": "R&D Hub", "ip": "10.1.6.6"},
    {"id": "fat_rig_1", "label": "F.A.T. Rig 1", "ip": "10.1.6.10"},
    {"id": "fat_rig_2", "label": "F.A.T. Rig 2", "ip": "10.1.6.11"},
    {"id": "fat_rig_3", "label": "F.A.T. Rig 3", "ip": "10.1.6.12"},
    {"id": "fat_rig_4", "label": "F.A.T. Rig 4", "ip": "10.1.6.13"},
    {"id": "right_hand_large_temperature_cabinet", "label": "Right Hand Large Temperature Cabinet", "ip": "10.1.6.14"},
    {"id": "left_hand_large_temperature_cabinet", "label": "Left Hand Large Temperature Cabinet", "ip": "10.1.6.15"},
    {"id": "right_hand_small_temperature_cabinet", "label": "Right Hand Small Temperature Cabinet", "ip": "10.1.6.16"},
    {"id": "left_hand_small_temperature_cabinet", "label": "Left Hand Small Temperature Cabinet", "ip": "10.1.6.17"},
    {"id": "twinsafe_temperature_cabinet", "label": "Twinsafe Temperature Cabinet", "ip": "10.1.6.18"},
    {"id": "signature_rig_1", "label": "Signature Rig 1", "ip": "10.1.6.19"},
    {"id": "signature_rig_2", "label": "Signature Rig 2", "ip": "10.1.6.20"},
    {"id": "prototype", "label": "Prototype", "ip": "10.1.6.40"},
]

RIG_IPS = {target["id"]: target["ip"] for target in RIG_TARGETS if target["ip"]}

# Rig overview OPC settings.
# Node IDs are identical across rigs.
RIG_OVERVIEW_FIELDS = (
    "rigName",
    "rigNo",
    "appName",
    "user",
    "rdReference",
    "testTitle",
    "currentPrompt",
    "updateAvailable",
)

RIG_OVERVIEW_OPC_PORT = 4840

RIG_OPC_ENDPOINTS = {
    target["id"]: f"opc.tcp://{target['ip']}:{RIG_OVERVIEW_OPC_PORT}"
    for target in RIG_TARGETS
    if target.get("ip")
}

RIG_OVERVIEW_NODE_IDS_TEMPLATE = {
    "rigName": "ns=4;s=|var|CODESYS Control for Linux ARM64 SL.DLS.GVL.stPersistentVars.sTestRigName",
    "rigNo": "ns=4;s=|var|CODESYS Control for Linux ARM64 SL.DLS.GVL.stPersistentVars.sTestRigNo",
    "appName": "ns=4;s=|var|CODESYS Control for Linux ARM64 SL.DLS.GVL.sAppName",
    "user": "ns=4;s=|var|CODESYS Control for Linux ARM64 SL.DLS.GVL.vumCurrentUser.wstFullName",
    "rdReference": "ns=4;s=|var|CODESYS Control for Linux ARM64 SL.DLS.GVL.asTestDetails[2,3]",
    "testTitle": "ns=4;s=|var|CODESYS Control for Linux ARM64 SL.DLS.GVL.sTestName",
    "currentPrompt": "ns=4;s=|var|CODESYS Control for Linux ARM64 SL.DLS.GVL.sPrompt",
    "updateAvailable": "ns=4;s=|var|CODESYS Control for Linux ARM64 SL.DLS.GVL.xUpdate",
}

RIG_OVERVIEW_NODE_IDS = {
    target["id"]: RIG_OVERVIEW_NODE_IDS_TEMPLATE.copy()
    for target in RIG_TARGETS
}
