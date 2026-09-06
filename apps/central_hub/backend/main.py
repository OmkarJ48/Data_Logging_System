from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import (
    ASSETS_DIR,
    FRONTEND_DIR,
    HUB_HISTORICAL_TREND_PAGE,
    PAGES_DIR,
    SHARED_HISTORICAL_TREND_PAGE,
    STYLES_DIR,
    WEBVISU_URL,
)
from .pages import deploy, pdf_generation, rig_status

app = FastAPI(title="R&D Central Hub")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pdf_generation.router)
app.include_router(deploy.router)
app.include_router(rig_status.router)


@app.on_event("startup")
async def startup_rig_status_service():
    rig_status.start_rig_status_service()


@app.on_event("shutdown")
async def shutdown_rig_status_service():
    rig_status.stop_rig_status_service()


def _redirect_preserving_query(request: Request, target: str) -> RedirectResponse:
    suffix = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(url=f"{target}{suffix}")


@app.middleware("http")
async def bounce_portal_host(request: Request, call_next):
    host = request.headers.get("host", "").split(":")[0].lower()
    if host == "rnd-portal.valves.co.uk":
        return RedirectResponse(url=WEBVISU_URL, status_code=302)

    path = request.url.path.rstrip("/") or "/"
    if path in {"/deploy", "/pages/deploy.html"} and not deploy.is_request_ip_allowed(request):
        return RedirectResponse(url="/static/index.html#rig-overview", status_code=302)

    return await call_next(request)


@app.get("/api/ping")
async def ping():
    return {"ok": True}


@app.get("/")
async def root():
    return RedirectResponse(url="/static/index.html")


@app.get("/rig-overview")
async def rig_overview_legacy():
    return RedirectResponse(url="/static/index.html#rig-overview")


@app.get("/getting-started")
async def getting_started_legacy():
    return RedirectResponse(url="/static/index.html#getting-started")


@app.get("/pdf-chart-generation")
async def pdf_chart_generation_legacy():
    return RedirectResponse(url="/static/index.html#pdf-chart-generation")


@app.get("/historical-trend")
async def historical_trend_legacy():
    return RedirectResponse(url="/static/index.html#historical-trend")


@app.get("/pages/historical_trend.html")
async def historical_trend_page(request: Request):
    if request.query_params.get("embed") == "1":
        return FileResponse(SHARED_HISTORICAL_TREND_PAGE)

    return FileResponse(HUB_HISTORICAL_TREND_PAGE)


@app.get("/pages/historical-trend.html")
async def shared_historical_trend_page_legacy(request: Request):
    return _redirect_preserving_query(request, "/pages/historical_trend.html")


@app.get("/pages/rig-overview.html")
async def rig_overview_page_legacy(request: Request):
    return _redirect_preserving_query(request, "/pages/rig_overview.html")


@app.get("/pages/getting-started.html")
async def getting_started_page_legacy(request: Request):
    return _redirect_preserving_query(request, "/pages/getting_started.html")


@app.get("/pages/pdf-chart-generation.html")
async def pdf_chart_generation_page_legacy(request: Request):
    return _redirect_preserving_query(request, "/pages/pdf_chart_generation.html")


@app.get("/deploy")
async def deploy_legacy():
    return RedirectResponse(url="/pages/deploy.html")


if PAGES_DIR.exists():
    app.mount("/pages", StaticFiles(directory=str(PAGES_DIR)), name="pages")
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")
if STYLES_DIR.exists():
    app.mount("/styles", StaticFiles(directory=str(STYLES_DIR)), name="styles")
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("apps.central_hub.backend.main:app", host="0.0.0.0", port=9000, reload=False)
