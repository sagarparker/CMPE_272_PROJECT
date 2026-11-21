"""Private HTTP retrieval API with model lifecycle and dependency readiness."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from mediamesh_ml.config import Settings
from mediamesh_ml.contracts import InvalidQuery
from mediamesh_ml.embeddings import ClipEngine
from mediamesh_ml.schemas import ErrorResponse, SearchMatch, SearchRequest, SearchResponse
from mediamesh_ml.search import SearchService
from mediamesh_ml.vectors import PgVectorRepository

logger = logging.getLogger(__name__)


def error_response(status, code, message):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def create_app(settings: Settings | None = None, *, search_service=None) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    service = (
        search_service
        if search_service is not None
        else SearchService(ClipEngine(settings), PgVectorRepository(settings))
    )

    @asynccontextmanager
    async def lifespan(_app):
        try:
            await asyncio.to_thread(service.initialize)
        except Exception as error:
            # Keep liveness available while readiness reports a missing model/cache.
            logger.warning("Search initialization failed: %s", type(error).__name__)
        yield

    app = FastAPI(title="MediaMesh ML", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.search_service = service

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _error: RequestValidationError) -> JSONResponse:
        return error_response(400, "INVALID_INPUT", "Invalid request input")

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, error: HTTPException) -> JSONResponse:
        messages = {404: "Resource not found", 405: "Method not allowed"}
        response = error_response(
            error.status_code,
            f"HTTP_{error.status_code}",
            messages.get(error.status_code, "Request could not be completed"),
        )
        if error.headers:
            response.headers.update(error.headers)
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness only; the route never loads a model or queries the database."""
        return {"status": "ok"}

    @app.get("/ready", responses={503: {"description": "Dependencies not ready"}})
    def ready() -> JSONResponse:
        available = service.is_ready()
        return JSONResponse(
            status_code=200 if available else 503,
            content={"status": "ready" if available else "not_ready"},
        )

    @app.post(
        "/internal/search",
        response_model=SearchResponse,
        responses={
            400: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    def search(body: SearchRequest):
        try:
            matches = service.search(body.query, body.limit)
            return SearchResponse(
                matches=[
                    SearchMatch(
                        asset_id=row.asset_id,
                        score=row.score,
                        frame_timestamp_seconds=row.frame_timestamp_seconds,
                    )
                    for row in matches
                ]
            )
        except InvalidQuery:
            return error_response(400, "INVALID_INPUT", "Invalid request input")
        except Exception as error:
            logger.warning("Search failed: %s", type(error).__name__)
            return error_response(503, "SEARCH_UNAVAILABLE", "Search dependencies are unavailable")

    def contract_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        for path in schema["paths"].values():
            for operation in path.values():
                responses = operation.get("responses", {})
                if responses.pop("422", None) is not None:
                    responses.setdefault("400", {"description": "Invalid request input"})
        app.openapi_schema = schema
        return schema

    app.openapi = contract_openapi
    return app
