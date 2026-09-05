"""Provider-independent tests never start real suggestion generation implicitly."""

import pytest

from signal_api.config import get_settings


@pytest.fixture(autouse=True)
def disable_automatic_suggestions(monkeypatch: pytest.MonkeyPatch) -> None:
    # Orchestration tests explicitly opt in with an injected model.
    monkeypatch.setattr(get_settings(), "suggestions_enabled", False)
