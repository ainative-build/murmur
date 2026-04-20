-- Fix: Supabase enables RLS on all tables by default.
-- Only personal_sources needs RLS (user isolation).
-- Other tables are accessed by the bot service, not end users directly.

ALTER TABLE messages DISABLE ROW LEVEL SECURITY;
ALTER TABLE link_summaries DISABLE ROW LEVEL SECURITY;
ALTER TABLE users DISABLE ROW LEVEL SECURITY;
ALTER TABLE user_chat_state DISABLE ROW LEVEL SECURITY;
ALTER TABLE draft_sessions DISABLE ROW LEVEL SECURITY;
ALTER TABLE exports DISABLE ROW LEVEL SECURITY;

-- personal_sources keeps RLS enabled (defense-in-depth)
-- but needs a policy that allows the bot's anon key to insert/select/delete
-- (app-layer filtering by tg_user_id is the primary privacy control)
DROP POLICY IF EXISTS personal_sources_user_isolation ON personal_sources;

-- Allow all operations via service role / anon key (bot is the only client)
CREATE POLICY personal_sources_bot_access ON personal_sources
    FOR ALL
    USING (true)
    WITH CHECK (true);
