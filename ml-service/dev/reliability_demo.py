"""Explicit local-only fault injection. Not copied into the normal runtime image."""
import asyncio
import os

from fastapi import Request
from fastapi.responses import JSONResponse

from mediamesh_ml.api import create_app as real_app


def create_app():
    if os.getenv("MEDIAMESH_LOCAL_DEMO") != "1":
        raise RuntimeError("Reliability simulation requires the explicit local demo override")
    app = real_app()
    delay = float(os.getenv("ML_DEMO_DELAY_SECONDS", "0"))
    fail = os.getenv("ML_DEMO_FAILURE", "false").lower() == "true"
    if not 0 <= delay <= 10:
        raise ValueError("Demo delay must be between zero and ten seconds")
    active = 0
    peak = 0

    @app.middleware("http")
    async def simulate(request: Request, call_next):
        nonlocal active, peak
        if request.method != "POST" or request.url.path != "/internal/search":
            return await call_next(request)
        active += 1
        peak = max(peak, active)
        try:
            if delay:
                await asyncio.sleep(delay)
            if fail:
                return JSONResponse(status_code=503, content={"error": {
                    "code": "SEARCH_UNAVAILABLE", "message": "Local simulation failure",
                }})
            return await call_next(request)
        finally:
            active -= 1

    @app.get("/dev/simulation")
    def simulation():
        return {"active": active, "peak": peak, "delaySeconds": delay, "forcedFailure": fail}

    return app
