Understood. Below is a fully academic, professional README with no emojis, suitable for direct submission and marking. You can copy and paste this over your existing README.md.

⸻

Sports Match and Performance Analytics API

This project implements a RESTful web service using FastAPI for managing sports teams, matches, players, and player performance statistics. The system extends beyond basic CRUD functionality by enforcing domain constraints, preserving referential integrity, and providing analytical insights derived from match and performance data.

The application has been developed in accordance with the COMP3011 Web Services coursework specification.

⸻

1. System Overview

The API supports the management of the following core entities:
	•	Teams
	•	Matches
	•	Players
	•	Player performance statistics (PlayerStats)

In addition to CRUD operations, the system provides analytics endpoints that compute team form, league tables, and player performance trends.

⸻

2. Architecture and Project Structure

The project follows a layered architecture to promote maintainability and separation of concerns.

app/
├── core/           Database configuration and session management
├── models/         SQLAlchemy ORM models
├── schemas/        Pydantic request and response schemas
├── repositories/  Data access layer
├── services/      Business logic and analytics computation
├── routers/        API endpoint definitions
└── main.py         Application entry point

tests/
├── conftest.py
├── test_core_endpoints.py
├── test_delete_constraints.py
├── test_stats.py
├── test_stats_advanced.py


⸻

3. Running the Application

3.1 Environment Setup

Create and activate a virtual environment:

python3 -m venv venv
source venv/bin/activate

Install dependencies:

pip install -r requirements.txt

3.2 Start the API Server

uvicorn app.main:app --reload

The service will be available at:

http://127.0.0.1:8000

Interactive API documentation is available at:
	•	Swagger UI: http://127.0.0.1:8000/docs
	•	ReDoc: http://127.0.0.1:8000/redoc

⸻

4. API Functionality

4.1 Teams
	•	POST /teams
	•	GET /teams
	•	GET /teams/{team_id}
	•	PUT /teams/{team_id}
	•	DELETE /teams/{team_id}

Deletion of a team is restricted if the team is referenced by one or more matches.

4.2 Matches
	•	POST /matches
	•	GET /matches
	•	GET /matches/{match_id}
	•	PUT /matches/{match_id}
	•	DELETE /matches/{match_id}

Validation ensures that the home and away teams are distinct.

4.3 Players and Statistics
	•	POST /players
	•	GET /players
	•	POST /stats
	•	GET /stats

Player statistics form a junction table between players and matches. A uniqueness constraint ensures that each player may have at most one statistics record per match.

⸻

5. Analytics Endpoints

The system includes multiple analytical endpoints that aggregate and compute insights from stored data.

5.1 Team Form

GET /analytics/team/{team_id}/form?last_n=5

Returns recent match results, wins, losses, points for and against, and win percentage.

5.2 League Table

GET /analytics/league/table

Returns teams ordered by total points, points difference, and points scored.

5.3 Player Performance Trend

GET /analytics/player/{player_id}/trend

Returns average performance metrics and a qualitative trend classification (improving, declining, or stable).

⸻

6. Testing Strategy

Automated integration tests are implemented using pytest and FastAPI’s TestClient.

6.1 Running Tests

pytest -q

6.2 Test Coverage

The test suite verifies:
	•	Prevention of duplicate team creation (409 Conflict)
	•	Domain validation for invalid matches (422 Unprocessable Entity)
	•	Enforcement of uniqueness constraints on player statistics
	•	Referential integrity when deleting teams
	•	Correctness of analytical computations and ordering

All tests are executed against an isolated in-memory SQLite database to ensure reproducibility and isolation.

⸻

7. Design Decisions
	•	Referential integrity is enforced at the application layer by restricting deletion of entities referenced by historical data.
	•	Analytics logic is implemented within a dedicated service layer to maintain separation from routing concerns.
	•	Clear and consistent HTTP status codes are used to communicate validation and conflict errors.

⸻

8. Limitations and Future Work
	•	Authentication and role-based authorisation
	•	Soft deletion for historical record preservation
	•	Pagination and filtering for analytics endpoints
	•	Support for configurable scoring systems
	•	Caching of analytical results for larger datasets

⸻

9. Generative AI Declaration

Generative AI tools were used during development for high-level architectural guidance, code structuring suggestions, and debugging assistance. All final design decisions, implementation, and verification were completed independently and comply with the module’s academic integrity requirements.

⸻

10. Project Status

The system is fully implemented, tested, and meets the coursework requirements for COMP3011 Web Services.
