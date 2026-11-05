-- ═══════════════════════════════════════════════════════════════════════════
-- PostgreSQL Row-Level Security — the Level-2 safety net (design doc §2.4).
--
-- Level 1 (always on): the application filters every query by org_id.
-- Level 2 (this script): the database itself refuses to return rows of a
-- different organisation, even if a developer forgets a filter.
--
-- Usage (production, after switching DATABASE_URL to PostgreSQL):
--   1. Run the app once so tables exist.
--   2. psql -d salesai -f scripts/postgres_rls.sql
--   3. Create the app's DB role and have the API set the org context per
--      connection/transaction:  SET LOCAL app.current_org_id = '<org_id>';
--      (add `SET LOCAL` in a SQLAlchemy event hook on checkout/begin)
-- ═══════════════════════════════════════════════════════════════════════════

-- The application must NOT connect as a superuser or table owner, otherwise
-- RLS is bypassed. Create a dedicated role:
--   CREATE ROLE salesai_app LOGIN PASSWORD '...';
--   GRANT USAGE ON SCHEMA public TO salesai_app;
--   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO salesai_app;

DO $$
DECLARE
    t text;
    org_tables text[] := ARRAY[
        'org_settings', 'leads', 'lead_state_history', 'contacts',
        'consent_records', 'client_intelligence', 'meetings', 'transcripts',
        'action_items', 'programs', 'pricing_tables', 'proposal_templates',
        'message_templates', 'proposals', 'proposal_revisions', 'demo_teams',
        'demo_team_members', 'demos', 'followups', 'outbound_messages',
        'message_delivery_log', 'memory_chunks', 'notifications',
        'assistant_turns'
    ];
BEGIN
    FOREACH t IN ARRAY org_tables LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS org_isolation ON %I', t);
        EXECUTE format(
            'CREATE POLICY org_isolation ON %I
             USING (org_id = current_setting(''app.current_org_id'', true))
             WITH CHECK (org_id = current_setting(''app.current_org_id'', true))',
            t
        );
    END LOOP;
END $$;

-- users.org_id is nullable (super admin) — scope but allow platform rows
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation ON users;
CREATE POLICY org_isolation ON users
    USING (org_id IS NULL OR org_id = current_setting('app.current_org_id', true))
    WITH CHECK (org_id IS NULL OR org_id = current_setting('app.current_org_id', true));

-- Recommended indexes beyond those created by the ORM (doc §11.1)
CREATE INDEX IF NOT EXISTS ix_leads_fts
    ON leads USING gin (to_tsvector('simple', name));
