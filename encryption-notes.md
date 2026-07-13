What I built
Encryption‑at‑rest for notes (AES‑256‑GCM), feature‑flagged, with the agent workflow kept intact and PII controls — all off by default, so nothing changes until you enable it.

Encryption (flag: notes.encryption)
crypto.py — AES‑256‑GCM with a versioned keyring. Token format enc:v<id>:<base64(nonce‖ct)>, random 96‑bit nonce, field‑label AAD, key‑version tag for rotation, legacy‑plaintext passthrough (mixed rows coexist → no big‑bang migration).
crypto_types.py — EncryptedText / EncryptedJSONB SQLAlchemy TypeDecorators. This is the key robustness choice: encryption happens at the column bind/result boundary, so Python always sees plaintext and the DB always holds ciphertext — safe across every path (create/update/move/tag/agent‑dispatch) with no risk of a stray commit() writing plaintext back.
note.py — title, description, content, content_text now use the encrypted types. Migration 20260703_02 widens title to TEXT (ciphertext exceeds 500 chars).
Key mgmt via env / AWS Secrets Manager (NOTES_ENCRYPTION_KEY, _KEY_ID, _KEYS_RETIRED), loaded through your existing secret loader. main.py fails fast at startup if the flag is on without a key.
Scalability: per‑request AES‑GCM is microseconds; keyring is cached; horizontal‑scale friendly (no per‑op KMS call).
Search trade‑off (as you chose: degrade to semantic)
Encrypting content_text/title breaks the Postgres FTS/ILIKE index. notes.py service skips SQL keyword search when encryption is on and filters the decrypted page in memory; full‑corpus search is served semantically via the agent/chat.

Agent workflow (the important part)
The agent reads note content directly from Postgres via raw SQL in two self‑healing paths — reconciliation.py and the authoritative re‑read in ingestion_tasks.py. Under encryption those return ciphertext, which would get embedded and silently corrupt retrieval. Fix: a decrypt‑only mirror agent crypto.py + shared key, decrypting those fields after read (no‑op for plaintext). Verified backend→agent interop with a shared key. The MCP surface reads content from Qdrant (plaintext derived chunks), not the notes table — no change needed. Qdrant caveat: it stores derived plaintext chunks, protected by network isolation (documented).

PII control (as you chose: redaction + egress flag)
Log redaction (always on): a structlog processor in both services (backend + agent via pii.py) scrubs emails/SSNs/cards/phones from every log value.
Egress control (flag: notes.pii_egress_control): notes.py blocks dispatching PII‑bearing notes to the external LLM/embedding pipeline (note still stored, encrypted) and logs it; the note response carries a computed has_pii tag.
Docs & tests
feature_flags.json notes group (both flags default false); SECRETS.md + .env.example document setup and rotation.
test_note_crypto.py covers crypto, the column types, and PII.
Verified
Crypto round‑trip, AAD field‑binding, GCM tamper rejection, key rotation, legacy passthrough, JSON, backend↔agent interop, and PII detect/redact all pass; every changed backend + agent file compiles.

Please note (couldn't run here)
No backend venv and the agent venv lacks pytest, so I verified via targeted execution + full py_compile, not the pytest suites. Please run pytest in both after rebuilding images (new deps: cryptography in both).
Enabling encryption requires the same NOTES_ENCRYPTION_KEY in backend and agent .env, and running migration 20260703_02.
Turning the flag on is safe on existing data (plaintext stays readable); turning it off later still reads previously‑encrypted rows as long as the key remains configured.
Want me to also switch the agent's reconciliation emptiness predicate from content_text to the unencrypted note_size column (tightens an edge case where encrypted‑empty notes get needlessly re‑processed), or wire a Celery‑beat check that both services agree on the key at startup?