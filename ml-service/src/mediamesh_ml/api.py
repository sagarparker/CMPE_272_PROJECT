"""HTTP foundation. Model/search/worker dependencies are wired in later steps."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from mediamesh_ml.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    app = FastAPI(title="MediaMesh ML", version="0.1.0")
    app.state.settings = settings

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "INVALID_INPUT", "message": "Invalid request input"}},
        )

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, error: HTTPException) -> JSONResponse:
        # Avoid reflecting arbitrary input or internal exception details.
        messages = {404: "Resource not found", 405: "Method not allowed"}
        return JSONResponse(
            status_code=error.status_code,
            headers=error.headers,
            content={
                "error": {
                    "code": f"HTTP_{error.status_code}",
                    "message": messages.get(error.status_code, "Request could not be completed"),
                }
            },
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness only; does not load or claim readiness of ML dependencies."""
        return {"status": "ok"}

    @app.get("/ready", responses={503: {"description": "Dependencies not ready"}})
    def ready() -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "reason": "ML dependencies are not wired yet"},
        )

    return app
