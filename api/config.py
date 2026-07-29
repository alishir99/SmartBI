"""API settings.

Note the two different database identities in play. The MCP server connects as
`app_readonly` and is subject to every RLS policy. The API connects as the owner, because
it has to read `app_user` (password hashes are never granted to the analytics role) and
write `audit_turn` and `saved_card`. Owner privileges bypass RLS, so every statement in
api/db.py carries its own `supplier_id` predicate — see the comment there.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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


settings = Settings()
