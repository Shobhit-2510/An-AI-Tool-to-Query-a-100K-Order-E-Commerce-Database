-- Defense-in-depth: a Postgres role that can ONLY read.
-- Run this once in the Supabase SQL editor against the Project A database.
-- The Text-to-SQL app connects as this user, so even if the LLM emits
-- DROP/DELETE/UPDATE the database itself rejects it.

CREATE ROLE t2sql_readonly LOGIN PASSWORD 'change-me-to-a-strong-password';

GRANT CONNECT ON DATABASE postgres TO t2sql_readonly;
GRANT USAGE  ON SCHEMA public      TO t2sql_readonly;

-- Read access to everything that exists now...
GRANT SELECT ON ALL TABLES IN SCHEMA public TO t2sql_readonly;

-- ...and to any table created later.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO t2sql_readonly;

-- Verify (should list only SELECT for this role):
-- SELECT grantee, privilege_type FROM information_schema.role_table_grants
-- WHERE grantee = 't2sql_readonly';
