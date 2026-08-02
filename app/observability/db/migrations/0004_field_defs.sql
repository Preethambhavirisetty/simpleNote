-- Registry of tracked field names. Rows are auto-created on first sighting at
-- ingest, so tracking a brand-new name never errors -- it just shows up in the
-- UI with sensible defaults. This is what makes the field set dynamic.
CREATE TABLE IF NOT EXISTS field_defs (
  name          VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  label         VARCHAR(128) NULL,
  kind          ENUM('text','number','json','bool') NOT NULL DEFAULT 'text',
  unit          VARCHAR(16) NULL,
  -- pinned fields become columns in the runs list and chips in the run header
  pinned        TINYINT(1) NOT NULL DEFAULT 0,
  display_order SMALLINT NOT NULL DEFAULT 100,
  -- how to collapse a field tracked N times within one run
  aggregate     ENUM('last','first','sum','avg','max','min','count')
                  NOT NULL DEFAULT 'last',
  first_seen_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  last_seen_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  use_count     BIGINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (name),
  KEY idx_field_defs_pinned (pinned, display_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
