-- Run once as a Postgres admin, AFTER the app has created its tables
-- (start the app or run the tests once with DATABASE_URL pointing at this database).
--
--   psql -U postgres -d cpa -v app_password="'change-me'" -f cpa_agents/store/sql/postgres_roles.sql
--
-- Creates the application role cpa_app. The append-only tables (audit_events, pack_versions,
-- section_versions, state_snapshots) get INSERT/SELECT only, so even with the triggers dropped
-- the application role cannot rewrite history. The tables must be owned by an admin role, not
-- cpa_app: an owner can always alter its own tables.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cpa_app') THEN
    CREATE ROLE cpa_app LOGIN;
  END IF;
END $$;
ALTER ROLE cpa_app PASSWORD :app_password;

GRANT CONNECT ON DATABASE cpa TO cpa_app;
GRANT USAGE ON SCHEMA public TO cpa_app;

-- append-only evidence tables
REVOKE ALL ON audit_events, pack_versions, section_versions, state_snapshots FROM cpa_app;
GRANT SELECT, INSERT ON audit_events, pack_versions, section_versions, state_snapshots TO cpa_app;

-- working tables
GRANT SELECT, INSERT, UPDATE ON cases, submissions, credit_queries TO cpa_app;

-- workflow runs and step jobs (LDU runtime): working tables, updated as runs progress
GRANT SELECT, INSERT, UPDATE ON runs, step_jobs TO cpa_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ldu_workers TO cpa_app;

-- workbench: users (password hashes) and uploaded document records
GRANT SELECT, INSERT, UPDATE ON users, documents TO cpa_app;

-- sequences behind the autoincrement ids
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cpa_app;

-- ADK session tables (created by DatabaseSessionService) need full DML
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['sessions', 'events', 'app_states', 'user_states', 'adk_internal_metadata'] LOOP
    IF to_regclass(t) IS NOT NULL THEN
      EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO cpa_app', t);
    END IF;
  END LOOP;
END $$;
