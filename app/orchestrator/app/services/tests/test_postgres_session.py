from unittest.mock import MagicMock, patch

import pytest

from app.db.postgres import DatabaseManager


def test_session_rolls_back_and_closes_after_exception():
    session = MagicMock()

    with patch.object(
        DatabaseManager,
        "get_session_factory",
        return_value=MagicMock(return_value=session),
    ):
        dependency = DatabaseManager.get_session()
        assert next(dependency) is session

        with pytest.raises(RuntimeError, match="route failed"):
            dependency.throw(RuntimeError("route failed"))

    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()
