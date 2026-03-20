

### Run mongo with podman:
podman run --detach --name my-mongo -p 27017:27017 docker.io/library/mongo:latest

### Run postgres with podman:
podman run -d \
  --name simple-note-postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=simplenote \
  -p 5432:5432 \
  docker.io/library/postgres:16

podman logs -f simple-note-postgres

For prod:
- Set up Alembic — create_all won't handle future schema changes
  - pip install alembic
  - alembic init alembic
- Set secure=True on the cookie in token.py (currently False for local HTTP dev)

BE:
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements
uvicorn app.main:app --port 3001 --reload

FE:
npm i
npm run dev

Tests:
python -m pytest tests/ -v


```
project_root/
├── app/
│   ├── api/                # Route handlers (Interface layer)
│   │   └── v1/             # Versioned API endpoints
│   │       ├── api.py      # Main router that includes all sub-routers
│   │       └── endpoints/  # Specific routes (e.g., users.py, items.py)
│   ├── core/               # App-wide configurations
│   │   ├── config.py       # Pydantic BaseSettings for env vars
│   │   └── security.py     # JWT, hashing, and auth logic
│   ├── db/                 # Database connection and session management
│   │   ├── base.py         # Import all models here for Alembic
│   │   └── session.py      # SQLAlchemy/Tortoise engine & session local
│   ├── models/             # Database models (SQLAlchemy/Tortoise)
│   ├── schemas/            # Pydantic models for request/response validation
│   ├── services/           # Complex business logic (Service layer)
│   ├── crud/               # Reusable CRUD operations
│   └── main.py             # App entry point; initializes FastAPI()
├── tests/                  # Unit and integration tests
├── alembic/                # Database migrations
├── .env                    # Environment variables
├── docker-compose.yml      # Container orchestration
└── pyproject.toml          # Dependency management (Poetry/Pip)
```


### Endpoints:

- Auth: (`/api/auth`)
  - `POST   /register`          — Register a new user, sets HTTP-only cookie
  - `POST   /login`             — Login, sets HTTP-only cookie
  - `DELETE /logout`            — Logout, clears cookie · *requires auth*
  - `PATCH  /change-password`   — Change own password · *requires auth*
  - `POST   /forgot-password`   — Request a 6-digit OTP reset code (sent via email)
  - `POST   /reset-password`    — Reset password using OTP code · max 5 attempts · 15 min expiry

- User: (`/api/users`)
  - Own profile · *requires auth*
    - `GET    /me`              — Get own profile
    - `PATCH  /me`              — Update own name / email
    - `DELETE /me`              — Delete own account

  - Admin only · *requires `admin` role*
    - `GET    /`                — List all users · supports `?skip=&limit=`
    - `GET    /{user_id}`       — Get any user by id
    - `PATCH  /{user_id}`       — Update any user's name / email
    - `DELETE /{user_id}`       — Delete any user
    - `PATCH  /{user_id}/roles`       — Assign roles to a user
    - `PATCH  /{user_id}/activate`    — Activate a user account
    - `PATCH  /{user_id}/deactivate`  — Deactivate a user account

- Folder: (`/api/folders`) · *requires auth*
  - `GET    /`                        — List own folders · pinned first · supports `?skip=&limit=`
  - `POST   /`                        — Create folder · 409 if name already exists
  - `GET    /{folder_id}`             — Get folder by id
  - `PATCH  /{folder_id}`             — Update folder name / is_pinned · 409 if new name conflicts
  - `DELETE /{folder_id}`             — Delete folder · notes become unfiled (not deleted)

- Notes: (`/api/notes`) · *requires auth*
  - `GET    /`                        — List own notes · supports `?folder_id`, `?pinned_only`, `?search`, `?skip`, `?limit`
  - `POST   /`                        — Create note · content_text auto-extracted from TipTap JSON
  - `GET    /{note_id}`               — Get note with tags
  - `PATCH  /{note_id}`               — Update note · content_text auto-updated when content changes
  - `PATCH  /{note_id}/move`          — Move note to a folder or inbox (`folder_id: null`)
  - `DELETE /{note_id}`               — Delete note
  - `POST   /{note_id}/tags/{tag_id}` — Add tag to note · 409 if already tagged
  - `DELETE /{note_id}/tags/{tag_id}` — Remove tag from note

- Tags: (`/api/tags`) · *requires auth*
  - `GET    /`                        — List own tags · alphabetical
  - `POST   /`                        — Create tag · 409 if name already exists
  - `GET    /{tag_id}`                — Get tag by id
  - `PATCH  /{tag_id}`                — Rename tag · 409 if new name conflicts
  - `DELETE /{tag_id}`                — Delete tag · removed from all notes automatically
