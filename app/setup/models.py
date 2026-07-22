from __future__ import annotations

import re
import ssl
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

_RDS_HOST_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+rds\.aliyuncs\.com$"
)


class SetupCodeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    setup_code: SecretStr = Field(min_length=16, max_length=256)


class DatabaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=63)
    username: str = Field(min_length=1, max_length=63)
    password: SecretStr = Field(min_length=1, max_length=1024)
    ssl_mode: Literal["verify-full"] = "verify-full"
    ca_pem: str = Field(min_length=64, max_length=256 * 1024)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        normalized = value.strip().lower().rstrip(".")
        if value != value.strip() or _RDS_HOST_PATTERN.fullmatch(normalized) is None:
            raise ValueError("host must be an Alibaba Cloud RDS hostname")
        return normalized

    @field_validator("database", "username")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if value != value.strip() or not value or any(ord(character) < 32 for character in value):
            raise ValueError("database identifiers must be canonical strings")
        return value

    @field_validator("ca_pem")
    @classmethod
    def validate_ca_pem(cls, value: str) -> str:
        normalized = value.strip() + "\n"
        if (
            "-----BEGIN CERTIFICATE-----" not in normalized
            or "-----END CERTIFICATE-----" not in normalized
        ):
            raise ValueError("ca_pem must contain a PEM certificate chain")
        try:
            ssl.create_default_context(cadata=normalized)
        except ssl.SSLError as error:
            raise ValueError("ca_pem must contain a valid CA certificate chain") from error
        return normalized

    def connection_components(self) -> dict[str, object]:
        return {
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "username": self.username,
            "password": self.password.get_secret_value(),
            "ssl_mode": self.ssl_mode,
        }


class InstallInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cloud_name: str = Field(min_length=1, max_length=128)
    public_base_url: str = Field(min_length=1, max_length=2048)
    database: DatabaseInput

    @field_validator("cloud_name")
    @classmethod
    def validate_cloud_name(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("cloud_name must be a canonical string")
        return value

    @field_validator("public_base_url")
    @classmethod
    def validate_public_base_url(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("public_base_url must be canonical")
        try:
            parsed = urlsplit(value)
            _port = parsed.port
        except ValueError as error:
            raise ValueError("public_base_url must be a valid HTTPS origin") from error
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("public_base_url must be an HTTPS origin without a path")
        hostname = str(parsed.hostname).lower()
        port = f":{parsed.port}" if parsed.port is not None else ""
        return f"https://{hostname}{port}"

    @model_validator(mode="after")
    def reject_cloud_origin_equal_to_database_host(self) -> InstallInput:
        if urlsplit(self.public_base_url).hostname == self.database.host:
            raise ValueError("public_base_url must not use the database hostname")
        return self
