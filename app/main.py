from fastapi import FastAPI
from app.core.database import Base, engine
from app.routers.teams import router as teams_router

def create_app() -> FastAPI:
    app = FastAPI(
        title="Sports Match & Performance Analytics API",
        version="1.0.0",
        description="REST API for teams, matches, players, and analytics.",
    )

    # Create database tables
    Base.metadata.create_all(bind=engine)

    # Health / root endpoint (professional polish)
    @app.get("/")
    def health_check():
        return {
            "status": "ok",
            "service": "sports-analytics-api"
        }

    # Routers
    app.include_router(teams_router, prefix="/teams", tags=["Teams"])

    return app


app = create_app()
