-- Track when last reminder was sent to enforce daily/weekly cadence
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_reminder_at TIMESTAMPTZ;
