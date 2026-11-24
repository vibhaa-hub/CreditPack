-- Upgrade an existing database for the LDU runtime (split-into-least-deployable-units).
-- Run as a Postgres admin AFTER the new tables exist (python -m cpa_agents.store.replay init,
-- run as the admin, creates `runs`, `step_jobs` and `ldu_workers`). Safe to run more than once; does not touch
-- the cpa_app password or any other grant.
--
--   psql -U postgres -d cpa -v ON_ERROR_STOP=1 -f cpa_agents/store/sql/upgrade_ldu_tables.sql

GRANT SELECT, INSERT, UPDATE ON runs, step_jobs TO cpa_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ldu_workers TO cpa_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cpa_app;
