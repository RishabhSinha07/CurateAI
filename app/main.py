from contextlib import asynccontextmanager
from typing import AsyncGenerator
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.api.routes.chat import router as chat_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup/shutdown events."""
    # Startup
    yield
    # Shutdown


app = FastAPI(
    title="CurateAI",
    description="Multi-agent AI consultation system for product recommendations",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


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
