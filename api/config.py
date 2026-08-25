"""API settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

# Ship-with-repo secrets so the demo needs no setup; each must be rotated before this serves
# anything outside dev. Checked in code, not a runbook, so a skipped rotation isn't silent.
IN_REPO_DEFAULTS = {
    "jwt_secret": "dev-only-change-me",
    "internal_token": "dev-internal-token",
    "postgres_password": "smartbi",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # `dev` is the demo posture: published internal ports, in-repo secrets, no TLS.
    smartbi_env: str = "prod"

    # The API's own Postgres connection, not the MCP role.
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "smartbi"
    postgres_user: str = "smartbi"
    postgres_password: str = "smartbi"

    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    # NIST 800-63B: length is what matters, composition rules just push weaker passwords.
    # The only rule, enforced everywhere a password is set.
    password_min_length: int = 8
    # Short by design: long enough to read the mail, short enough to matter if the inbox is
    # later compromised. Single-use is enforced separately (see password_reset_key).
    password_reset_ttl_minutes: int = 60
    # Separate short-lived signed token from the access token, so a leaked share URL can't
    # be replayed as a login.
    share_link_ttl_hours: int = 72

    mcp_url: str = "http://localhost:8081/mcp"
    # Shared secret proving the caller is this API, not something else on the internal port.
    internal_token: str = "dev-internal-token"
    mcp_timeout_seconds: float = 60.0

    # LLM provider lives behind these three values and nothing else (decision D1).
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/anthropic"
    llm_model: str = "deepseek-v4-pro"
    llm_max_tokens: int = 8000
    # SDK default is 10 min per request with 2 retries - one question could hold a
    # connection 30+ min unbounded.
    llm_timeout_seconds: float = 60.0

    # Rate limits (api/ratelimit.py): generous for a human, tight for a script - a limit
    # that trips mid-demo is worse than none.
    login_window_seconds: int = 300
    # A human retyping a password gets it wrong 2-3 times (capslock, an old saved password).
    login_attempts_per_identifier: int = 5
    # Higher: an office/demo room shares one NAT address; locking out a building isn't better.
    login_attempts_per_ip: int = 30

    # A turn is several LLM calls, 10-30s; 10/5min is already faster than a human reads
    # answers, but a human isn't the binding constraint here.
    chat_turns_per_user: int = 100
    chat_window_seconds: int = 300

    # Per-tenant cap on trailing-window tokens (from audit_turn). ~30k tokens/turn puts 5M at
    # ~150 turns/day, above a heavy day but far below a runaway client in an hour.
    tenant_token_budget: int | None = 5_000_000
    tenant_budget_window_hours: int = 24

    # Logging (api/logs.py): json for anything shipped, text for local runs. File handler is
    # always JSON - a log you have to regex is a log nobody aggregates.
    log_level: str = "INFO"
    log_format: str = "json"
    # Empty = stdout only, what the container wants (docker/Cloud Run collect stdout; a file
    # in a container is a file nobody reads). Set only for a direct local run.
    log_file: str = ""
    # Off everywhere but a laptop: stdout is a WIDER trust boundary than the DB (which sits
    # behind RLS). On, it puts question text and rejected figures back into the log.
    log_sensitive: bool = False
    # Rotated by time not size: size-based rotation gives no fixed window ("last 120MB" is 2h
    # busy / 6mo quiet), so "what happened last Tuesday" needs daily files with day retention.
    log_retention_days: int = 14

    # Mail (api/mail.py): `log` writes to the app log for local/demo use, `smtp` sends for
    # real. stdlib smtplib only - a provider SDK is a dependency, an account, another failure mode.
    mail_backend: str = "log"  # log | smtp
    mail_from: str = "no-reply@smartbi.example"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True

    # Locale: point these at the real market and every amount/date/axis label follows.
    # app_currency must match mcp_server/config.py - same warehouse, one truth.
    app_currency: str = "SEK"  # ISO-4217
    app_locale: str = "sv-SE"  # BCP-47
    app_language: str = "sv"  # UI/answer language, see LANGUAGES

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    public_web_url: str = "http://localhost:5173"

    @property
    def dsn(self) -> str:
        return (f"postgresql://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}")

    def unrotated_secrets(self) -> list[str]:
        """Which guarded fields still hold the value published in this repository."""
        if self.smartbi_env.strip().lower() == "dev":
            return []
        return sorted(name for name, default in IN_REPO_DEFAULTS.items()
                      if getattr(self, name) == default)

    def assert_secrets_rotated(self) -> None:
        """Fail closed at boot on secrets anyone can read out of the repository."""
        if unchanged := self.unrotated_secrets():
            raise RuntimeError(
                f"api: refusing to start with the in-repo default for "
                f"{', '.join(unchanged)}. These values are public - anyone who can read "
                f"the repository can mint a session with them. Set real values, or set "
                f"SMARTBI_ENV=dev to run the local demo.")


settings = Settings()
