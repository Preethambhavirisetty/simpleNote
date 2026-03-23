"""
Simulation script — observe how the Celery ingestion queue handles concurrent
note creation across multiple users.

Flow per simulated user:
  1. Register (sets auth cookie automatically)
  2. Create a folder
  3. Create a note inside that folder  ← triggers queue dispatch
  4. Print result

Run:
  python3 simulate.py          # 5 users (default)
  python3 simulate.py 10       # 10 concurrent users
"""
import asyncio
import sys
import httpx

BACKEND_URL = "http://localhost:3001/api"

# httpx timeout: registration + note creation can be slow on first run
TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)

NOTE_CONTENT = {
    "type": "doc",
    "content": [
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": (
                        'The "System Failure" Stress Test\n'
                        "text\nUPLOADED_FILE_FINAL_v2_USE_THIS_ONE.txt\n"
                        "User: @Marketing_Lead | Date: 2026-05-12\n\n"
                        "1. CAMPAIGN OVERVIEW\n"
                        'We are launching "Project Zenith." It\'s going to be huge.\n\n'
                        "2. AUDIENCE SEGMENTATION (DRAFT)\n"
                        "* Tier 1: Early Adopters\n"
                        "    - Age: 18-24\n"
                        '    - Interest: Tech, AI, "Crypto"\n'
                        "* Tier 2: Enterprise\n"
                        "    - Size: 500+ Employees\n\n"
                        "BUDGET BREAKDOWN\n"
                        "Ads $50,000 Approved @John\n"
                        "Social $12,000 Pending @Sarah\n"
                        "Influencers $30,000 Review @Mike\n\n"
                        "TO-DO LIST\n"
                        "Design the logo\n"
                        "Hire a copywriter\n"
                        "Prepare the @Legal_Team brief\n\n"
                        "[END OF TRANSMISSION]"
                    ),
                }
            ],
        }
    ],
}


async def simulate_user(user_index: int, client: httpx.AsyncClient) -> None:
    """Run the full register → folder → note flow for one simulated user."""
    tag = f"[user-{user_index}]"
    email = f"sim_user_{user_index}@notelite.dev"
    password = "Simulate123!"
    name = f"SimUser{user_index}"

    # ── 1. Register (also logs in — sets the auth cookie) ────────────────────
    reg_resp = await client.post(
        f"{BACKEND_URL}/auth/register",
        json={"name": name, "email": email, "password": password, "role": ["standard_user"]},
    )
    if reg_resp.status_code not in (200, 201):
        # User likely already exists from a previous run — try logging in instead
        print(f"{tag} register returned {reg_resp.status_code}, trying login...")
        login_resp = await client.post(
            f"{BACKEND_URL}/auth/login",
            json={"email": email, "password": password},
        )
        if login_resp.status_code not in (200, 201):
            print(f"{tag} login also failed ({login_resp.status_code}): {login_resp.text[:200]}")
            return
        print(f"{tag} logged in ✓")
    else:
        print(f"{tag} registered ✓")

    # ── 2. Create a folder ────────────────────────────────────────────────────
    folder_resp = await client.post(
        f"{BACKEND_URL}/folders/",
        json={"name": f"SimFolder-{user_index}"},
    )
    if folder_resp.status_code not in (200, 201):
        print(f"{tag} folder creation failed ({folder_resp.status_code}): {folder_resp.text[:200]}")
        return
    folder_id = folder_resp.json()["data"]["id"]
    print(f"{tag} folder created: {folder_id}")

    # ── 3. Create a note (this triggers the ingestion + compute_note_size queue dispatch) ──
    note_resp = await client.post(
        f"{BACKEND_URL}/notes/",
        json={
            "title": f"Stress-test note #{user_index}",
            "folder_id": folder_id,
            "description": f"Simulation note for user {user_index}",
            "content": NOTE_CONTENT,
            "is_pinned": False,
        },
    )
    if note_resp.status_code not in (200, 201):
        print(f"{tag} note creation failed ({note_resp.status_code}): {note_resp.text[:200]}")
        return

    data = note_resp.json()["data"]
    print(
        f"{tag} note created ✓  "
        f"note_id={data['id']}  version={data.get('version', '?')}  "
        f"→ ingestion task dispatched to queue"
    )


async def run_simulation(count: int) -> None:
    print(f"\n{'─'*60}")
    print(f"  Simulating {count} concurrent users against {BACKEND_URL}")
    print(f"{'─'*60}\n")

    # Each user gets their own client so cookies don't bleed between users.
    async def _run(i: int) -> None:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            try:
                await simulate_user(i, client)
            except httpx.ConnectError:
                print(f"[user-{i}] ✗ Could not connect to {BACKEND_URL} — is the backend running?")
            except httpx.ReadTimeout:
                print(f"[user-{i}] ✗ Request timed out — backend may be overloaded or slow to start")
            except Exception as exc:  # noqa: BLE001
                print(f"[user-{i}] ✗ Unexpected error: {exc}")

    await asyncio.gather(*[_run(i+1000) for i in range(count)])
    print(f"\n{'─'*60}")
    print("  All users done. Watch the Celery worker logs to see the queue drain.")
    print(f"{'─'*60}\n")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    asyncio.run(run_simulation(n))
