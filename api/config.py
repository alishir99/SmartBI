"""API settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

# Secrets that ship in the repo so the demo runs with no setup, and the value each one has to
# move off before this process is allowed to serve anything outside `dev`. Keeping the check in
# code rather than in a deployment runbook is the point: a runbook can be skipped by whoever
# inherits this, and the failure mode of a skipped rotation is silent.
IN_REPO_DEFAULTS = {
    "jwt_secret": "dev-only-change-me",
    "internal_token": "dev-internal-token",
    "postgres_password": "solvigo",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # `dev` is the demo posture: published internal ports, in-repo secrets, no TLS.
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
    # Share links are their own short-lived signed token, deliberately separate from the access
    # token so a leaked share URL cannot be replayed as a login (§10).
    share_link_ttl_hours: int = 72

    # --- MCP ---
    mcp_url: str = "http://localhost:8081/mcp"
    # Shared secret proving the caller is this API and not something else that found the
    # internal port.
    internal_token: str = "dev-internal-token"
    mcp_timeout_seconds: float = 60.0

    # --- LLM --- Provider lives behind these three values and nothing else (decision D1).
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/anthropic"
    llm_model: str = "deepseek-v4-pro"
    llm_max_tokens: int = 8000
    # The SDK's own default is 10 minutes per request and it retries twice, so one question
    # could hold a connection for over half an hour before anything gave up.
    llm_timeout_seconds: float = 60.0

    # --- Rate limits and cost cap (api/ratelimit.py) --- Every limit here is picked to be
    # generous for a human and tight for a script, because a limit that trips during a live demo
    # is worse than no limit at all.
    login_window_seconds: int = 300
    # A human retyping a password gets it wrong two or three times — capslock, an old saved
    # password.
    login_attempts_per_identifier: int = 5
    # Higher, because an office (or a demo room) shares one NAT address, and locking out a whole
    # building because one person forgot their password is its own outage.
    login_attempts_per_ip: int = 30

    # A chat turn is several LLM calls and takes 10–30 s, so ten in five minutes is already
    # faster than a person can read the answers — but a human is not the binding constraint
    # here.
    chat_turns_per_user: int = 100
    chat_window_seconds: int = 300

    # Per-tenant cost cap, in input+output tokens over the trailing window, read from
    # `audit_turn`. Sized from the measured ~30 k tokens a turn costs: 5 M is roughly 150 turns
    # a day for one supplier, several times the heaviest realistic day and far below what a
    # runaway client burns in an hour.
    tenant_token_budget: int | None = 5_000_000
    tenant_budget_window_hours: int = 24

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
        """Fail closed at boot on secrets anyone can read out of the repository."""
        if unchanged := self.unrotated_secrets():
            raise RuntimeError(
                f"api: refusing to start with the in-repo default for "
                f"{', '.join(unchanged)}. These values are public — anyone who can read "
                f"the repository can mint a session with them. Set real values, or set "
                f"SOLVIGO_ENV=dev to run the local demo.")


settings = Settings()
