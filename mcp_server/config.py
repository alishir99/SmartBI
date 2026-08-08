"""MCP server settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict

# Mirrors api/config.py's IN_REPO_DEFAULTS - keep both in sync.
IN_REPO_DEFAULTS = {
    "internal_token": "dev-internal-token",
    "app_db_password": "app_readonly",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Default is the published demo posture: open port, in-repo secrets.
    solvigo_env: str = "prod"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "solvigo"

    app_db_user: str = "app_readonly"
    app_db_password: str = "app_readonly"

    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8081

    # Shared secret between the API and the MCP server.
    internal_token: str = "dev-internal-token"

    # Hard ceiling on query duration in Postgres, independent of anything the caller sets.
    statement_timeout_ms: int = 15_000

    # Every tool result states this in meta, so a figure never reaches a card without its unit.
    # Must match api/config.py's app_currency - same warehouse, one answer.
    app_currency: str = "SEK"
    prices_include_vat: bool = False

    @property
    def vat_code(self) -> str:
        return "incl" if self.prices_include_vat else "excl"

    @property
    def dsn(self) -> str:
        return (f"postgresql://{self.app_db_user}:{self.app_db_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}")

    def unrotated_secrets(self) -> list[str]:
        """Which guarded fields still hold the value published in this repository."""
        if self.solvigo_env.strip().lower() == "dev":
            return []
        return sorted(name for name, default in IN_REPO_DEFAULTS.items()
                      if getattr(self, name) == default)

    def assert_secrets_rotated(self) -> None:
        """Fail closed at boot on secrets anyone can read out of the repository."""
        if unchanged := self.unrotated_secrets():
            raise RuntimeError(
                f"mcp_server: refusing to start with the in-repo default for "
                f"{', '.join(unchanged)}. These values are public - anyone who can read "
                f"the repository can call the internal tool surface with them. Set real "
                f"values, or set SOLVIGO_ENV=dev to run the local demo.")


settings = Settings()
