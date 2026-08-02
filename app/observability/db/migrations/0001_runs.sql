-- One run = one user question, from ask to final answer.
CREATE TABLE IF NOT EXISTS runs (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  run_key         VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  conversation_id VARCHAR(128) NULL,
  question        TEXT NULL,
  final_answer    MEDIUMTEXT NULL,
  status          ENUM('running','ok','error') NOT NULL DEFAULT 'running',
  error_message   TEXT NULL,
  started_at      DATETIME(6) NOT NULL,
  ended_at        DATETIME(6) NULL,
  duration_ms     INT UNSIGNED NULL,
  log_count       INT UNSIGNED NOT NULL DEFAULT 0,
  error_count     INT UNSIGNED NOT NULL DEFAULT 0,
  max_seq         INT UNSIGNED NOT NULL DEFAULT 0,
  metadata_json   JSON NULL,
  created_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  -- client-generated key: the agent can reference a run before the DB assigns
  -- anything, and a retried POST is a no-op instead of a duplicate run
  UNIQUE KEY uk_runs_key (run_key),
  KEY idx_runs_recent       (started_at DESC, id DESC),
  KEY idx_runs_status       (status, started_at DESC, id DESC),
  KEY idx_runs_conversation (conversation_id, started_at DESC),
  KEY idx_runs_errors       (error_count, started_at DESC),
  FULLTEXT KEY ft_runs_question (question)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
