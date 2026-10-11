-- Private service-role database only. Never expose these tables to browser clients.
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
 salt TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('user','master')),
 created DOUBLE PRECISION NOT NULL, last_seen DOUBLE PRECISION NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower ON users(lower(username));
CREATE TABLE IF NOT EXISTS sessions (
 hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
 user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 revision INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL DEFAULT '{}', updated DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS global_config (
 id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, payload TEXT NOT NULL
);
INSERT INTO global_config VALUES(1,0,'{"menu_labels":{}}') ON CONFLICT DO NOTHING;
-- On Supabase deployments restrict every table to trusted server service_role.
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE global_config ENABLE ROW LEVEL SECURITY;
-- No anonymous/authenticated policies are granted. The service database owner bypasses RLS.
