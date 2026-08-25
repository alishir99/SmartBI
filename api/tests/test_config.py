"""The settings refuse to boot on secrets that are published in this repository (§11)."""

from __future__ import annotations

import pytest

from api.config import IN_REPO_DEFAULTS as API_DEFAULTS
from api.config import Settings as ApiSettings
from mcp_server.config import IN_REPO_DEFAULTS as MCP_DEFAULTS
from mcp_server.config import Settings as McpSettings

REAL = {"jwt_secret": "a-real-secret", "internal_token": "a-real-token",
        "postgres_password": "a-real-password", "app_db_password": "another-real-password"}

SERVICES = [pytest.param(ApiSettings, API_DEFAULTS, id="api"),
            pytest.param(McpSettings, MCP_DEFAULTS, id="mcp")]


def build(cls, defaults: dict, *, smartbi_env: str = "prod", **overrides):
    """Construct settings, then run the check the entrypoints run at boot."""
    values = {**defaults, "smartbi_env": smartbi_env, **overrides}
    settings = cls(_env_file=None, **values)
    settings.assert_secrets_rotated()
    return settings


def rotated(defaults: dict) -> dict:
    return {name: REAL[name] for name in defaults}


# ------------------------------------------------------------------------- it fails closed

@pytest.mark.parametrize("cls,defaults", SERVICES)
def test_the_shipped_defaults_are_refused_outside_dev(cls, defaults):
    with pytest.raises(RuntimeError) as caught:
        build(cls, defaults)

    message = str(caught.value)
    for name in defaults:
        assert name in message, f"{name} borde nämnas i felet"


@pytest.mark.parametrize("cls,defaults", SERVICES)
def test_one_unrotated_secret_is_enough_to_refuse(cls, defaults):
    """Rotating all but one and missing the last must not pass."""
    for laggard in defaults:
        values = rotated(defaults)
        values[laggard] = defaults[laggard]

        with pytest.raises(RuntimeError) as caught:
            build(cls, defaults, **values)

        assert laggard in str(caught.value)


@pytest.mark.parametrize("cls,defaults", SERVICES)
def test_the_error_never_prints_the_value(cls, defaults):
    """A boot failure lands in a log aggregator. It may name the field, never the secret."""
    with pytest.raises(RuntimeError) as caught:
        build(cls, defaults)

    message = str(caught.value)
    for name, secret in defaults.items():
        assert secret not in message, f"värdet för {name} läckte ut i felmeddelandet"


@pytest.mark.parametrize("cls,defaults", SERVICES)
@pytest.mark.parametrize("value", ["prod", "production", "staging", "", "development", "devx"])
def test_only_dev_exactly_opts_in(cls, defaults, value):
    with pytest.raises(RuntimeError):
        build(cls, defaults, smartbi_env=value)


@pytest.mark.parametrize("cls,defaults", SERVICES)
def test_production_is_the_default_posture(cls, defaults):
    """Forgetting to set SMARTBI_ENV must not be a way into the demo posture."""
    assert cls.model_fields["smartbi_env"].default == "prod"


# --------------------------------------------------------------------------- it still boots

@pytest.mark.parametrize("cls,defaults", SERVICES)
@pytest.mark.parametrize("value", ["dev", "DEV", " dev "])
def test_dev_permits_the_demo_defaults(cls, defaults, value):
    """The local demo has to keep working with nothing but the checked-in .env.example."""
    settings = build(cls, defaults, smartbi_env=value)

    for name, default in defaults.items():
        assert getattr(settings, name) == default


@pytest.mark.parametrize("cls,defaults", SERVICES)
def test_rotated_secrets_boot_without_dev(cls, defaults):
    settings = build(cls, defaults, **rotated(defaults))

    for name in defaults:
        assert getattr(settings, name) == REAL[name]


@pytest.mark.parametrize("cls,defaults", SERVICES)
def test_every_guarded_field_exists_with_that_default(cls, defaults):
    """Guards against a rename quietly turning the whole check into a no-op."""
    for name, default in defaults.items():
        field = cls.model_fields.get(name)
        assert field is not None, f"{cls.__name__} saknar fältet {name}"
        assert field.default == default, f"{cls.__name__}.{name} har bytt standardvärde"


def test_importing_the_packages_never_raises():
    """The reason this is a startup check: `import api.config` has to work everywhere."""
    import importlib

    for module in ("api.config", "mcp_server.config", "api.main"):
        assert importlib.import_module(module) is not None


# ------------------------------------------------------------------- the check is wired in

@pytest.fixture
def unconfigured(monkeypatch):
    """Put both singletons back on their published defaults, as an unset environment would."""
    from api import config as api_config
    from mcp_server import config as mcp_config

    for module, defaults in ((api_config, API_DEFAULTS), (mcp_config, MCP_DEFAULTS)):
        monkeypatch.setattr(module.settings, "smartbi_env", "prod")
        for name, default in defaults.items():
            monkeypatch.setattr(module.settings, name, default)


async def test_the_api_refuses_to_start_before_it_opens_anything(unconfigured, monkeypatch):
    """The check has to run ahead of the pool and ahead of the port, not alongside them."""
    from api import db, main

    def fail(*args, **kwargs):
        raise AssertionError("startade uppkoppling trots att hemligheterna var kvar")

    monkeypatch.setattr(db, "init_pool", fail)

    with pytest.raises(RuntimeError, match="refusing to start"):
        async with main.lifespan(main.app):
            pass


def test_the_mcp_server_refuses_to_start(unconfigured, monkeypatch):
    from mcp_server import db, server

    monkeypatch.setattr(db, "init_pool", lambda *a, **k: pytest.fail("startade uppkoppling"))

    with pytest.raises(RuntimeError, match="refusing to start"):
        server.main()
