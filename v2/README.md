

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
pip install alembic
alembic init alembic

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

```
app/
  api/
    v1/
      endpoints/
        users.py
        billing.py
        notes.py
        folders.py
        blocks.py
  deps/
    auth.py
  core/
    config.py
    security.py

  db/
    postgres/
      session.py
      base.py
      models/
        user.py
        billing.py
      repositories/
        user_repo.py
        billing_repo.py
    mongo/
      client.py
      documents/
        notes.py
        folders.py
        blocks.py
      repositories/
        notes_repo.py
        folders_repo.py
        blocks_repo.py

  services/
    auth.py
    billing.py
    notes.py
    folders.py
    blocks.py
```

```
Auth Service
   │
   ├── PostgreSQL (users)
   │
   └── JWT tokens

API Service
   │
   ├── MongoDB
   │      folders
   │      notes
   │      blocks
   │
   └── get_current_user() dependency
```








To use Beanie effectively in your FastAPI routes, you treat your classes (like User or Notes) as the interface to the database.
Here is how you perform CRUD operations. Note that all methods are async because Beanie is built on top of the Motor driver.
1. Create (Insert)
You just initialize the class and call .insert().

@app.post("/users")async def create_user(user_data: User):
    # .insert() saves it to MongoDB and returns the created document
    await user_data.insert()
    return user_data

2. Read (Find)
Beanie provides a very readable API for searching.

@app.get("/notes/{note_id}")async def get_note(note_id: UUID):
    # Find a single document by its ID
    note = await Notes.get(note_id)
    if not note:
        return {"error": "Not found"}
    return note

@app.get("/notes/user/{user_id}")async def get_user_notes(user_id: UUID):
    # Find multiple documents with a filter
    notes = await Notes.find(Notes.user_id == user_id).to_list()
    return notes

3. Update
You can modify the object in Python and then sync it to the database.

@app.patch("/notes/{note_id}/archive")async def archive_note(note_id: UUID):
    note = await Notes.get(note_id)
    if note:
        note.isArchived = True
        note.updatedAt = datetime.now(timezone.utc)
        await note.save() # Saves the changes
    return note

4. Delete

@app.delete("/notes/{note_id}")async def delete_note(note_id: UUID):
    note = await Notes.get(note_id)
    if note:
        await note.delete()
    return {"message": "Deleted successfully"}

Pro-Tip: Beanie vs. Pydantic
In Beanie, your model must inherit from Document instead of BaseModel to get these database methods.

from beanie import Document
class User(Document):
    # ... your fields here ...
    class Settings:
        name = "users" # The MongoDB collection name

Why this is "Stable" for Scaling:

* Query Engine: Beanie uses MongoDB's native query operators, which are highly optimized.
* Validation: It validates data before it hits the database, preventing "corrupt" documents.
* Integration: It works perfectly with FastAPI's dependency injection system.

Do you want to see how to add custom indexes to these models to speed up your searches as your data grows?

