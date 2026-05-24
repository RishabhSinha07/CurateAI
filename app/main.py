from contextlib import asynccontextmanager
from typing import AsyncGenerator
import logging
import json
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings
from app.api.routes.chat import router as chat_router
from app.api.routes.events import router as events_router
from app.api.routes.admin import router as admin_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.middleware.logging import RequestLoggingMiddleware

settings = get_settings()

# Configure logging - JSON format for production (CloudWatch)
if settings.environment == "production":
    class JsonFormatter(logging.Formatter):
        def format(self, record):
            log_obj = {
                "timestamp": self.formatTime(record, self.datefmt),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            # Include extra fields from structured logging
            for key in ("request_id", "tenant_id", "method", "path",
                        "status_code", "duration_ms", "client_ip",
                        "agent", "session_id"):
                if hasattr(record, key):
                    log_obj[key] = getattr(record, key)
            if record.exc_info:
                log_obj["exception"] = self.formatException(record.exc_info)
            return json.dumps(log_obj)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        handlers=[handler]
    )
else:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup/shutdown events."""
    # Startup
    logger.info(f"Starting CurateAI in {settings.environment} mode")
    logger.info(f"Database configured: {settings.database_url is not None}")
    logger.info(f"Using DB graphs: {settings.use_db_graphs}")

    # Preload YAML-based knowledge graphs at startup (Phase 1)
    if not settings.use_db_graphs:
        try:
            from app.knowledge.graph_loader import list_available_graphs
            graphs = list_available_graphs()
            logger.info(f"Loaded {len(graphs)} YAML-based knowledge graphs: {graphs}")
        except Exception as e:
            logger.error(f"Failed to load knowledge graphs: {e}", exc_info=True)

    # Import the vertical registry so verticals self-register at startup
    # (fail fast on misconfiguration instead of on first request).
    from app.agents.shared.registry import registered_verticals
    logger.info(f"Registered verticals: {registered_verticals()}")

    yield
    # Shutdown
    logger.info("Shutting down CurateAI")


app = FastAPI(
    title="CurateAI",
    description="Multi-agent AI consultation system for product recommendations",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,  # Disable in production
    redoc_url="/redoc" if settings.environment != "production" else None,
)

# Request logging middleware (outermost — measures full request duration)
app.add_middleware(RequestLoggingMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check() -> dict:
    """
    Enhanced health check with DB connectivity.

    Returns 200 with status "healthy" or "degraded".
    """
    checks = {}

    # DB connectivity check
    try:
        from app.db.session import engine
        if engine:
            from sqlalchemy import text
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        else:
            checks["database"] = "not_configured"
    except Exception as e:
        checks["database"] = f"error: {str(e)[:100]}"

    overall = "healthy" if checks.get("database") in ("ok", "not_configured") else "degraded"

    return {"status": overall, "checks": checks}


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {"message": "Welcome to CurateAI API"}


@app.get("/test/graph")
async def test_graph() -> dict:
    """Test knowledge graph integration."""
    try:
        from app.knowledge.query_engine import GraphQueryEngine
        from app.knowledge.graph_loader import list_available_graphs

        graphs = list_available_graphs()
        test_problem = GraphQueryEngine.extract_problem_from_text("wellness", "tired")

        return {
            "status": "success",
            "available_graphs": graphs,
            "test_query": {
                "input": "tired",
                "result": test_problem
            }
        }
    except Exception as e:
        logger.error(f"Graph test failed: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e)
        }


# Include routers
app.include_router(chat_router)
app.include_router(events_router)
app.include_router(admin_router)
app.include_router(dashboard_router)
