"""
FastAPI application entry point.
"""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.api.v1.routers import (
    health, uploads, jobs, reconciliation, exceptions, analytics, pricing, reports
)

settings = get_settings()
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FinOps AI starting", environment=settings.environment)
    yield
    logger.info("FinOps AI shutting down")


app = FastAPI(
    title="FinOps AI — Payment Reconciliation & Gateway Cost Intelligence",
    description=(
        "API for importing gateway payment data, running reconciliation, "
        "detecting exceptions, and analyzing gateway costs."
    ),
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.perf_counter()
    response: Response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
        request_id=request_id,
    )
    return response


# Routers
app.include_router(health.router, tags=["Health"])
app.include_router(uploads.router, prefix="/api/v1", tags=["Uploads"])
app.include_router(jobs.router, prefix="/api/v1", tags=["Import Jobs"])
app.include_router(reconciliation.router, prefix="/api/v1", tags=["Reconciliation"])
app.include_router(exceptions.router, prefix="/api/v1", tags=["Exceptions"])
app.include_router(analytics.router, prefix="/api/v1", tags=["Analytics"])
app.include_router(pricing.router, prefix="/api/v1", tags=["Pricing"])
app.include_router(reports.router, prefix="/api/v1", tags=["Reports"])


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", error=str(exc), path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Check server logs for details."},
    )
