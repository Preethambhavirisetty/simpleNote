-- The selectively-tracked values: playbook, resource, operation, latency,
-- tokens, scores, conversation state, memory, ... and anything you add later.
--
-- Three value columns rather than one JSON blob. value_num and value_text are
-- separately indexed, so "avg latency by playbook" and "runs where score < 0.5"
-- are index-served. MySQL JSON columns are not directly indexable, so a single
-- JSON column would turn every such query into a full scan.
CREATE TABLE IF NOT EXISTS tracked_fields (
  id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  run_id     BIGINT UNSIGNED NOT NULL,
  log_id     BIGINT UNSIGNED NULL,
  seq        INT UNSIGNED NOT NULL,
  name       VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  value_text VARCHAR(512) NULL,
  value_num  DECIMAL(20,6) NULL,
  value_json JSON NULL,
  unit       VARCHAR(16) NULL,
  ts         DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_tf_run_seq_name (run_id, seq, name),
  KEY idx_tf_run_name  (run_id, name, seq),
  KEY idx_tf_name_num  (name, value_num),
  KEY idx_tf_name_text (name, value_text),
  KEY idx_tf_log       (log_id),
  CONSTRAINT fk_tf_run FOREIGN KEY (run_id) REFERENCES runs (id) ON DELETE CASCADE,
  CONSTRAINT fk_tf_log FOREIGN KEY (log_id) REFERENCES logs (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
