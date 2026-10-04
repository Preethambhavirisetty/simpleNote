import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from app.core import feature_flags


@pytest.fixture
def flags_file(tmp_path, monkeypatch):
    original_state = (
        copy.deepcopy(feature_flags._flags),
        feature_flags._flags_source_path,
        feature_flags._flags_resolved_path,
        feature_flags._flags_signature,
    )
    flags = {
        "chat": {
            "enabled": True,
            "children": {
                f"option_{index}": {"enabled": False}
                for index in range(8)
            },
        },
        "notes": {
            "enabled": True,
            "children": {
                "encryption": {"enabled": False},
                "pii_egress_control": {"enabled": False},
            },
        },
    }
    path = tmp_path / "feature_flags.json"
    path.write_text(json.dumps(flags))
    monkeypatch.setattr(feature_flags, "_FLAGS_PATH", str(path))

    yield path

    with feature_flags._flags_lock:
        (
            feature_flags._flags,
            feature_flags._flags_source_path,
            feature_flags._flags_resolved_path,
            feature_flags._flags_signature,
        ) = original_state


def test_flag_reads_refresh_after_file_changes(flags_file):
    feature_flags.load_flags()
    assert feature_flags.is_enabled("chat.option_0") is False

    flags = json.loads(flags_file.read_text())
    flags["chat"]["children"]["option_0"]["enabled"] = True
    flags_file.write_text(json.dumps(flags))

    assert feature_flags.is_enabled("chat.option_0") is True

    flags["chat"]["children"]["option_0"]["enabled"] = False
    flags_file.write_text(json.dumps(flags))
    assert feature_flags.get_all_resolved()["chat.option_0"] is False


def test_concurrent_toggles_do_not_lose_updates(flags_file):
    names = [f"option_{index}" for index in range(8)]
    barrier = threading.Barrier(len(names))

    def enable(name):
        barrier.wait()
        return feature_flags.toggle_flag(name, True)

    with ThreadPoolExecutor(max_workers=len(names)) as executor:
        assert all(executor.map(enable, names))

    persisted = json.loads(flags_file.read_text())
    assert all(
        persisted["chat"]["children"][name]["enabled"]
        for name in names
    )


@pytest.mark.parametrize(
    "name",
    [
        "notes",
        "encryption",
        "notes.encryption",
        "pii_egress_control",
        "notes.pii_egress_control",
    ],
)
def test_security_sensitive_flags_cannot_be_toggled_at_runtime(flags_file, name):
    before = flags_file.read_text()

    with pytest.raises(HTTPException) as exc_info:
        feature_flags.toggle_flag(name, True)

    assert exc_info.value.status_code == 403
    assert flags_file.read_text() == before
