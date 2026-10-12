# CloudCollab — Cloud Based Remote Work Collaboration System

A learning/demo prototype for a cloud-hosted team workspace. It includes account registration/login, team workspaces, member joining by team ID, file upload/download, and an activity history.

## Features
- Register/login with password hashing (PBKDF2) and signed expiring bearer tokens
- Create a team workspace; share its numeric team ID with classmates to join
- Team-specific file sharing (20 MB per-file demo limit)
- Activity feed for account/team/file actions
- Docker image + Docker Compose persistent volume
- Health endpoint at `/api/health`

## Run locally (Python)
Requires Python 3.10+.
```bash
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --reload
```
Open http://127.0.0.1:8000

## Run with Docker
Install Docker Desktop, open this folder in PowerShell, then:
```bash
docker compose up --build
```
Open http://localhost:8000. Stop with Ctrl+C; run `docker compose down`. Data persists in the named volume. `docker compose down -v` deletes that volume.

## Demo flow
1. Register User A and create a team.
2. Note the team ID displayed in the team list.
3. Register User B in a separate browser/incognito window.
4. User B uses “Join by Team ID” with User A's team ID.
5. Upload a file as either member, then download it and inspect Activity.
6. Check `http://localhost:8000/api/health`.

## Cloud concepts to explain in your report
- **Container virtualization:** Docker packages the app and its dependencies in an isolated container.
- **Provisioning:** Docker Compose defines the service, port, environment variables and persistent volume.
- **Persistence:** the named volume keeps uploaded files and SQLite database across container restarts.
- **Elasticity (prototype demonstration):** run multiple stateless app replicas behind a reverse proxy/load balancer after moving SQLite to PostgreSQL and file storage to S3-compatible object storage. Do not simply scale this SQLite/local-volume demo as-is; local state is not shared safely across replicas.
- **Resource pooling:** cloud provider resources are shared and allocated to multiple teams; the demo simulates multiple teams in one app.

## Important limitations
Educational prototype only—not production-ready. Before public deployment add HTTPS, stronger secret management, email verification/password reset, rate limiting, malware scanning, file type policies, admin audit controls, database migrations, PostgreSQL/object storage, automated backups, and tests. The demo's “join by team ID” is intentionally simple; production should use invite links/codes with expiry and permissions.

## Suggested report structure
1. Introduction and problem statement
2. Objectives and scope
3. Literature review: IaaS/PaaS/SaaS, virtualization, resource pooling, elasticity
4. System requirements and architecture
5. Use-case diagram and database design
6. Implementation and screenshots
7. Docker deployment and elasticity experiment
8. Testing and results
9. Limitations and future scope
10. Conclusion
