import pytest
from pydantic import ValidationError

from aiseoonline_api.config import Settings
from aiseoonline_api.main import create_app


def test_optional_model_key_is_not_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AISEO_OPENAI_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    assert settings.openai_api_key is None
    assert create_app(settings).state.settings is settings


def test_settings_override_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AISEO_ENVIRONMENT", "test")
    monkeypatch.setenv("AISEO_API_PORT", "9001")
    settings = Settings(_env_file=None)
    assert settings.environment == "test"
    assert settings.api_port == 9001


def test_invalid_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AISEO_ENVIRONMENT", "unsafe")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_invalid_port_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AISEO_API_PORT", "70000")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_model_key_repr_is_redacted() -> None:
    settings = Settings(_env_file=None, openai_api_key="sample-do-not-log")
    assert "sample-do-not-log" not in repr(settings)
