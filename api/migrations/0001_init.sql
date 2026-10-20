CREATE TABLE authors (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('ai', 'person')),
  created_at TEXT NOT NULL
);

CREATE TABLE primers (
  archetype TEXT PRIMARY KEY,
  format TEXT NOT NULL,
  title TEXT NOT NULL,
  current_version INTEGER NOT NULL,
  written_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE primer_versions (
  archetype TEXT NOT NULL,
  version INTEGER NOT NULL,
  author_id TEXT NOT NULL REFERENCES authors (id),
  markdown TEXT NOT NULL,
  document TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (archetype, version)
);

CREATE TABLE ratings (
  archetype TEXT NOT NULL,
  install_id TEXT NOT NULL,
  value INTEGER NOT NULL CHECK (value IN (-1, 1)),
  updated_at TEXT NOT NULL,
  PRIMARY KEY (archetype, install_id)
);
