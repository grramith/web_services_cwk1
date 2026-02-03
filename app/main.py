from fastapi import FastAPI
from app.core.database import Base, engine
from app.routers.teams import router as teams_router

def create_app() -> FastAPI:
    app = FastAPI(
        title="Sports Match & Performance Analytics API",
        version="1.0.0",
        description="REST API for teams, matches, players, and analytics."
    )

    # Create tables (fine for coursework; later you can move to Alembic)
    Base.metadata.create_all(bind=engine)

    app.include_router(teams_router, prefix="/teams", tags=["Teams"])
    return app

app = create_app()
