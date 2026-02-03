import os

def get_database_url() -> str:
    # Default to SQLite for coursework/dev
    return os.getenv("DATABASE_URL", "sqlite:///./sports.db")
