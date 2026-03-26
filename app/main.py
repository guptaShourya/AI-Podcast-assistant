import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.database import engine
from app.db.models import Base

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created")

    yield

    # Shutdown
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

    app.include_router(router)

    return app


app = create_app()
