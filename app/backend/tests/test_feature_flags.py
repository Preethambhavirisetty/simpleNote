import copy
import json

from app.core import feature_flags


def test_flag_reads_refresh_after_file_changes(tmp_path, monkeypatch):
    original_state = (
        copy.deepcopy(feature_flags._flags),
        feature_flags._flags_source_path,
        feature_flags._flags_resolved_path,
        feature_flags._flags_signature,
    )
    path = tmp_path / "feature_flags.json"
    flags = {
        "chat": {
            "enabled": True,
            "children": {"streaming": {"enabled": False}},
        }
    }
    path.write_text(json.dumps(flags))
    monkeypatch.setattr(feature_flags, "_FLAGS_PATH", str(path))

    try:
        feature_flags.load_flags()
        assert feature_flags.is_enabled("chat.streaming") is False

        flags["chat"]["children"]["streaming"]["enabled"] = True
        path.write_text(json.dumps(flags))

        assert feature_flags.is_enabled("chat.streaming") is True

        flags["chat"]["children"]["streaming"]["enabled"] = False
        path.write_text(json.dumps(flags))
        assert feature_flags.get_all_resolved()["chat.streaming"] is False
    finally:
        with feature_flags._flags_lock:
            (
                feature_flags._flags,
                feature_flags._flags_source_path,
                feature_flags._flags_resolved_path,
                feature_flags._flags_signature,
            ) = original_state
