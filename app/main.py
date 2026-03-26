import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db.database import engine
from app.db.models import Base
from app.mcp.server import mcp
from app.scheduler.jobs import start_scheduler, stop_scheduler

logger = logging.getLogger(__name__)

mcp_app = mcp.http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables + start scheduler + MCP lifespan
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created")
    start_scheduler()

    async with mcp_app.router.lifespan_context(app):
        yield

    # Shutdown
    stop_scheduler()
    await engine.dispose()
    logger.info("Database engine disposed")


def create_app() -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = FastAPI(
        title="AI Podcast Summary Assistant",
        description="Automatically transcribe and summarize podcast episodes",
        version="0.1.0",
        lifespan=lifespan,
    )

    from app.api.routes import router
    from app.ui.views import router as ui_router

    app.include_router(router)
    app.include_router(ui_router)
    app.mount("/static", StaticFiles(directory="app/ui/static"), name="static")
    app.mount("/", mcp_app)

    return app


app = create_app()
