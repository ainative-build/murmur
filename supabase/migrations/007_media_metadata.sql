-- Add media_type and source_filename columns for voice/audio/file message tracking
ALTER TABLE messages ADD COLUMN IF NOT EXISTS media_type TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS source_filename TEXT;
-- media_type values: 'voice', 'audio', 'file', 'photo', NULL (text-only)
-- source_filename: original filename for file attachments, NULL for voice/text
