-- Migration script to convert users.id from integer to VARCHAR(255)

BEGIN;

-- Step 1: Drop foreign key constraint from documents
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_user_id_fkey;

-- Step 2: Create temporary table with VARCHAR ID
CREATE TABLE users_new (
    id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Step 3: Copy users with converted IDs
INSERT INTO users_new (id, name, email, password_hash, created_at)
SELECT 'user_' || id::text, name, email, password_hash, created_at
FROM users;

-- Step 4: Update documents table - alter column type
ALTER TABLE documents ALTER COLUMN user_id TYPE VARCHAR(255) USING user_id::text;

-- Step 5: Update document user_ids to match new user IDs
UPDATE documents d
SET user_id = 'user_' || d.user_id
WHERE user_id ~ '^[0-9]+$';

-- Step 6: Drop old users table and rename new one
DROP TABLE users CASCADE;
ALTER TABLE users_new RENAME TO users;

-- Step 7: Recreate foreign key constraint
ALTER TABLE documents
ADD CONSTRAINT documents_user_id_fkey
FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- Step 8: Recreate indexes
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents(user_id);

COMMIT;

