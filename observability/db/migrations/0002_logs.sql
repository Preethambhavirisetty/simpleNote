-- The flat log stream. Add as many lines as you like, anywhere in the agent.
CREATE TABLE IF NOT EXISTS logs (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  run_id      BIGINT UNSIGNED NOT NULL,
  -- seq is the ordering authority, not ts: parallel work lands on the same
  -- microsecond and clocks drift, but seq is a single counter per run
  seq         INT UNSIGNED NOT NULL,
  ts          DATETIME(6) NOT NULL,
  level       ENUM('DEBUG','INFO','WARN','ERROR') NOT NULL DEFAULT 'INFO',
  -- VARCHAR not ENUM on purpose: new phases appear as the agent grows and
  -- should never require a migration
  phase       VARCHAR(64) NULL,
  message     TEXT NOT NULL,
  source      VARCHAR(255) NULL,
  data_json   JSON NULL,
  duration_ms INT UNSIGNED NULL,
  created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  -- doubles as timeline order and as free idempotency for re-POSTed batches
  UNIQUE KEY uk_logs_run_seq (run_id, seq),
  KEY idx_logs_run_level (run_id, level, seq),
  KEY idx_logs_run_phase (run_id, phase, seq),
  KEY idx_logs_level_ts  (level, ts DESC),
  FULLTEXT KEY ft_logs_message (message),
  CONSTRAINT fk_logs_run FOREIGN KEY (run_id) REFERENCES runs (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
