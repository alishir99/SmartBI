"""API settings.

Note the two different database identities in play. The MCP server connects as
`app_readonly` and is subject to every RLS policy. The API connects as the owner, because
it has to read `app_user` (password hashes are never granted to the analytics role) and
write `audit_turn` and `saved_card`. Owner privileges bypass RLS, so every statement in
api/db.py carries its own `supplier_id` predicate — see the comment there.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

# Secrets that ship in the repo so the demo runs with no setup, and the value each one has
# to move off before this process is allowed to serve anything outside `dev`. Keeping the
# check in code rather than in a deployment runbook is the point: a runbook can be skipped
# by whoever inherits this, and the failure mode of a skipped rotation is silent.
IN_REPO_DEFAULTS = {
    "jwt_secret": "dev-only-change-me",
    "internal_token": "dev-internal-token",
    "postgres_password": "solvigo",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # `dev` is the demo posture: published internal ports, in-repo secrets, no TLS. It has
    # to be asked for explicitly, so that forgetting to configure an environment fails
    # closed rather than quietly inheriting the laptop defaults.
    solvigo_env: str = "prod"

    # --- Postgres (the API's own connection, not the MCP role) ---
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "solvigo"
    postgres_user: str = "solvigo"
    postgres_password: str = "solvigo"

    # --- Auth ---
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    # Share links are their own short-lived signed token, deliberately separate from the
    # access token so a leaked share URL cannot be replayed as a login (§10).
    share_link_ttl_hours: int = 72

    # --- MCP ---
    mcp_url: str = "http://localhost:8081/mcp"
    # Shared secret proving the caller is this API and not something else that found the
    # internal port. Same default as mcp_server/config.py.
    internal_token: str = "dev-internal-token"
    mcp_timeout_seconds: float = 60.0

    # --- LLM ---
    # Provider lives behind these three values and nothing else (decision D1). Pointing
    # them at api.anthropic.com + claude-opus-5 moves the whole agent to real Claude.
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/anthropic"
    llm_model: str = "deepseek-v4-pro"
    llm_max_tokens: int = 8000

    # --- Web ---
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    public_web_url: str = "http://localhost:5173"

    @property
    def dsn(self) -> str:
        return (f"postgresql://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}")

    def unrotated_secrets(self) -> list[str]:
        """Which guarded fields still hold the value published in this repository."""
        if self.solvigo_env.strip().lower() == "dev":
            return []
        return sorted(name for name, default in IN_REPO_DEFAULTS.items()
                      if getattr(self, name) == default)

    def assert_secrets_rotated(self) -> None:
        """Fail closed at boot on secrets anyone can read out of the repository.

        A startup check rather than a field validator, deliberately. `settings` is a
        module-level singleton, so validating on construction would make `import
        api.config` raise in every unconfigured environment — CI, a reviewer's clean clone,
        a test run — and a guarantee that breaks `pytest` gets deleted by the next person
        rather than obeyed. Refusing to *serve* is the property that matters; this runs
        from the lifespan handler, which is the moment the process starts serving.

        Field names are reported; their values never are, since the one string here that is
        guaranteed to reach a log aggregator is this one.

        Duplicated in mcp_server/config.py rather than shared: the two services deploy
        independently and neither imports the other, so a common settings module would be
        the only edge between them and would exist solely to save a dozen lines.
        """
        if unchanged := self.unrotated_secrets():
            raise RuntimeError(
                f"api: refusing to start with the in-repo default for "
                f"{', '.join(unchanged)}. These values are public — anyone who can read "
                f"the repository can mint a session with them. Set real values, or set "
                f"SOLVIGO_ENV=dev to run the local demo.")


settings = Settings()
