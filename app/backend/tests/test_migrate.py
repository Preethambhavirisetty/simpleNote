"""Migration-runner adoption logic (app.db.migrate).

The decision must stamp the *baseline* (not head) for pre-Alembic databases and
run a plain upgrade in every other state.
"""
from app.db.migrate import BASELINE_REVISION, plan_migration


def test_pre_alembic_database_is_adopted():
    """Tables exist but no version row — the old create_all schema."""
    assert plan_migration(current_revision=None, has_users_table=True) == "stamp_then_upgrade"


def test_fresh_database_gets_plain_upgrade():
    """Empty database: upgrade builds everything from the baseline."""
    assert plan_migration(current_revision=None, has_users_table=False) == "upgrade"


def test_already_stamped_database_gets_plain_upgrade():
    assert plan_migration(current_revision=BASELINE_REVISION, has_users_table=True) == "upgrade"


def test_database_on_later_revision_gets_plain_upgrade():
    assert plan_migration(current_revision="20990101_99", has_users_table=True) == "upgrade"


def test_baseline_revision_matches_the_migration_file():
    """The stamp target must be a real revision or adoption bricks the startup."""
    import pathlib

    versions = pathlib.Path(__file__).parents[1] / "alembic" / "versions"
    revisions = [
        line.split("=")[1].strip().strip('"')
        for path in versions.glob("*.py")
        for line in path.read_text().splitlines()
        if line.startswith("revision =")
    ]
    assert BASELINE_REVISION in revisions
