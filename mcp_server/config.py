"""MCP server settings.

Note the database user: the MCP server connects as `app_readonly`, which holds SELECT and
nothing else and is subject to every RLS policy in db/sql/04_rls.sql. The seeder and the
rollup refresh run as the owner on a different connection entirely.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

# See the matching block in api/config.py. Secrets that ship in the repo so the demo runs
# with no setup, and the value each has to move off before the process serves anything
# outside `dev`.
IN_REPO_DEFAULTS = {
    "internal_token": "dev-internal-token",
    "app_db_password": "app_readonly",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The demo posture — published internal port, in-repo secrets. Asked for explicitly, so
    # that an unconfigured environment fails closed instead of inheriting laptop defaults.
    solvigo_env: str = "prod"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "solvigo"

    app_db_user: str = "app_readonly"
    app_db_password: str = "app_readonly"

    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8081

    # Shared secret between the API and the MCP server. The MCP server is not exposed to
    # the internet (§11.4), but "not routable" is a deployment property and this is a
    # property of the code — cheap defence in depth against the day someone changes the
    # ingress setting.
    internal_token: str = "dev-internal-token"

    # Hard ceiling on rows a single tool call may return, independent of the caller's limit.
    statement_timeout_ms: int = 15_000

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
        """Fail closed at boot on secrets anyone can read out of the repository.

        This one matters more than the API's. `internal_token` is the *only* thing between
        the tool surface and anyone who can reach the MCP port — with the in-repo value a
        caller sets the supplier header to whatever they like and reads any tenant's rows.

        A startup check rather than a field validator, for the reason spelled out in
        api/config.py: `settings` is a module-level singleton, and validating on
        construction would make importing this package raise in CI and in every clean
        clone. Field names are reported; values are not.
        """
        if unchanged := self.unrotated_secrets():
            raise RuntimeError(
                f"mcp_server: refusing to start with the in-repo default for "
                f"{', '.join(unchanged)}. These values are public — anyone who can read "
                f"the repository can call the internal tool surface with them. Set real "
                f"values, or set SOLVIGO_ENV=dev to run the local demo.")


settings = Settings()
