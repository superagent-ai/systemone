from functools import cached_property

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SYSTEMONE_", env_file=".env", extra="ignore", case_sensitive=False
    )

    api_keys: SecretStr = SecretStr("")
    api_keys_secondary: SecretStr = SecretStr("")
    backend_url: str = "http://127.0.0.1:30000"
    backend_api_key: SecretStr = SecretStr("")
    model_path: str = ""
    served_model: str = "security-one"
    model_aliases: str = "security-one-latest,systemone,systemone-latest,openjev,jev-latest"
    release_date: str = "2026-09-25"

    max_body_bytes: int = Field(default=1_048_576, ge=1_024, le=16_777_216)
    max_questions: int = Field(default=64, ge=1, le=64)
    max_answers: int = Field(default=16, ge=2, le=16)
    max_input_tokens: int = Field(default=65_536, ge=256, le=65_536)
    max_total_input_tokens: int = Field(default=131_072, ge=256)
    max_concurrent_requests: int = Field(default=32, ge=1, le=1_024)
    max_concurrent_branches: int = Field(default=128, ge=1, le=4_096)
    request_timeout_seconds: float = Field(default=120, gt=0, le=600)
    startup_timeout_seconds: float = Field(default=900, gt=0, le=3_600)
    temperature: float = Field(default=0.14527332485151376, gt=0, le=10)

    @field_validator("backend_url")
    @classmethod
    def strip_backend_url(cls, value: str) -> str:
        return value.rstrip("/")

    @cached_property
    def accepted_models(self) -> tuple[str, ...]:
        values = [self.served_model, *(item.strip() for item in self.model_aliases.split(","))]
        return tuple(dict.fromkeys(item for item in values if item))

    @cached_property
    def accepted_api_keys(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                item.strip()
                for configured in (
                    self.api_keys.get_secret_value(),
                    self.api_keys_secondary.get_secret_value(),
                )
                for item in configured.split(",")
                if item.strip()
            )
        )
