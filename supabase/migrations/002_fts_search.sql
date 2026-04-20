-- Full-text search support using 'simple' config (mixed-language chats)

ALTER TABLE messages ADD COLUMN IF NOT EXISTS search_vector tsvector;
ALTER TABLE link_summaries ADD COLUMN IF NOT EXISTS search_vector tsvector;
ALTER TABLE personal_sources ADD COLUMN IF NOT EXISTS search_vector tsvector;

CREATE INDEX IF NOT EXISTS idx_messages_fts ON messages USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_links_fts ON link_summaries USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_personal_fts ON personal_sources USING GIN(search_vector);

-- Auto-populate search vectors on insert/update
CREATE OR REPLACE FUNCTION update_messages_search() RETURNS trigger AS $$
BEGIN
  NEW.search_vector := to_tsvector('simple', COALESCE(NEW.text, ''));
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION update_links_search() RETURNS trigger AS $$
BEGIN
  NEW.search_vector := to_tsvector('simple',
    COALESCE(NEW.title, '') || ' ' || COALESCE(NEW.summary, '') || ' ' || COALESCE(NEW.extracted_content, ''));
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION update_personal_search() RETURNS trigger AS $$
BEGIN
  NEW.search_vector := to_tsvector('simple',
    COALESCE(NEW.title, '') || ' ' || COALESCE(NEW.content, '') || ' ' || COALESCE(NEW.summary, ''));
  RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS messages_search_trigger ON messages;
CREATE TRIGGER messages_search_trigger
  BEFORE INSERT OR UPDATE ON messages
  FOR EACH ROW EXECUTE FUNCTION update_messages_search();

DROP TRIGGER IF EXISTS links_search_trigger ON link_summaries;
CREATE TRIGGER links_search_trigger
  BEFORE INSERT OR UPDATE ON link_summaries
  FOR EACH ROW EXECUTE FUNCTION update_links_search();

DROP TRIGGER IF EXISTS personal_search_trigger ON personal_sources;
CREATE TRIGGER personal_search_trigger
  BEFORE INSERT OR UPDATE ON personal_sources
  FOR EACH ROW EXECUTE FUNCTION update_personal_search();
