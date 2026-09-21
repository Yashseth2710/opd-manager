"""Application settings, loaded from the environment."""

from __future__ import annotations

import secrets
import ssl
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]

# libpq understands these; asyncpg raises TypeError on them. Neon puts both in
# the string it hands you, so they are stripped and SSL is passed separately.
_LIBPQ_ONLY = {"sslmode", "channel_binding", "options", "target_session_attrs"}


def _to_asyncpg(url: str) -> str:
    """Rewrite a stock Postgres URL into one the asyncpg driver accepts."""
    if not url:
        return url

    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in {"postgres", "postgresql"}:
        scheme = "postgresql+asyncpg"

    query = "&".join(
        f"{key}={value}"
        for key, value in parse_qsl(parts.query)
        if key.lower() not in _LIBPQ_ONLY
    )
    return urlunsplit((scheme, parts.netloc, parts.path, query, parts.fragment))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "preview", "production", "test"] = "development"
    version: str = "0.1.0"

    database_url: str = Field(default="")
    database_direct_url: str = Field(default="")

    # Signing key for access tokens. A generated fallback keeps a fresh clone
    # runnable, at the cost of invalidating every session on restart.
    jwt_secret: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    access_token_minutes: int = 15
    refresh_token_days: int = 7

    upstash_redis_rest_url: str = Field(default="")
    upstash_redis_rest_token: str = Field(default="")

    # Where the links in outgoing email point.
    app_url: str = "http://localhost:3000"

    # Brevo verifies a single sender address rather than a whole domain, so
    # mail reaches any recipient without owning one. Resend needs a verified
    # domain but is the better choice once there is one.
    brevo_api_key: str = Field(default="")
    resend_api_key: str = Field(default="")
    mail_from: str = "OPD Manager <onboarding@resend.dev>"

    # Patient documents. Vercel Blob in any deployed environment; with no token
    # in development they are written under local_files_dir instead, so the
    # browser suite runs without an account.
    blob_read_write_token: str = Field(default="")
    blob_api_url: str = "https://vercel.com/api/blob"
    local_files_dir: Path = ROOT / ".files"

    @property
    def storage(self) -> Literal["blob", "local", "none"]:
        if self.blob_read_write_token:
            return "blob"
        return "local" if self.environment == "development" else "none"

    @property
    def email_configured(self) -> bool:
        """With no provider the application says so rather than reporting a
        delivery that never happened."""
        return bool(self.brevo_api_key or self.resend_api_key)

    @property
    def mail_sender(self) -> tuple[str, str]:
        """Splits `Name <address>` into the two fields providers ask for."""
        raw = self.mail_from.strip()
        if "<" in raw and raw.endswith(">"):
            name, _, address = raw.partition("<")
            return name.strip() or "OPD Manager", address[:-1].strip()
        return "OPD Manager", raw

    @property
    def redis_configured(self) -> bool:
        return bool(self.upstash_redis_rest_url and self.upstash_redis_rest_token)

    @field_validator("database_url", "database_direct_url")
    @classmethod
    def _normalise(cls, value: str) -> str:
        return _to_asyncpg(value)

    @property
    def alembic_url(self) -> str:
        """Migrations use the direct endpoint. A transaction pooler cannot hold
        the session-level locks that DDL needs."""
        return self.database_direct_url or self.database_url

    @property
    def is_local_database(self) -> bool:
        host = urlsplit(self.database_url).hostname or ""
        return host in {"localhost", "127.0.0.1", "::1", ""}

    @property
    def connect_args(self) -> dict[str, Any]:
        args: dict[str, Any] = {}

        # Anything reached over a network gets TLS. Deciding this from the
        # environment name instead would demand SSL of a Postgres running
        # beside the tests, which refuses the upgrade and fails the run.
        if not self.is_local_database:
            args["ssl"] = ssl.create_default_context()

        # PgBouncer in transaction mode does not guarantee the same backend
        # across statements, which breaks asyncpg's prepared statement cache.
        if "-pooler." in self.database_url:
            args["statement_cache_size"] = 0

        return args

    @property
    def is_pooled(self) -> bool:
        return "-pooler." in self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
