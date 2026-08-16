"""Main FastAPI application."""

import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Snack GPT",
        description="Local-first wellness food logger",
        version="0.1.0",
    )

    # Include API router
    from snack_gpt.api.routes import router
    app.include_router(router)

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok"}

    return app


app = create_app()
