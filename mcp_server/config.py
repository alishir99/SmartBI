"""MCP server settings.

Note the database user: the MCP server connects as `app_readonly`, which holds SELECT and
nothing else and is subject to every RLS policy in db/sql/04_rls.sql. The seeder and the
rollup refresh run as the owner on a different connection entirely.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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


settings = Settings()
