from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./acil.db"
    api_key: str = "acil-dev-key"
    log_level: str = "INFO"
    google_cloud_project: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ACIL_GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_PROJECT"),
    )
    google_cloud_location: str = Field(
        default="global",
        validation_alias=AliasChoices("ACIL_GOOGLE_CLOUD_LOCATION", "GOOGLE_CLOUD_LOCATION"),
    )
    google_application_credentials: str | None = Field(
        default=None, validation_alias="GOOGLE_APPLICATION_CREDENTIALS"
    )
    gemini_judge_model: str = Field(
        default="gemini-3.5-flash-lite",
        validation_alias=AliasChoices("ACIL_GEMINI_JUDGE_MODEL", "GEMINI_MODEL"),
    )
    gemini_auth_mode: str = Field(
        default="vertex_adc",
        validation_alias=AliasChoices("ACIL_GEMINI_AUTH_MODE", "GEMINI_AUTH_MODE"),
    )
    gemini_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ACIL_GEMINI_API_KEY", "GEMINI_API_KEY"),
    )
    gemini_thinking_level: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ACIL_GEMINI_THINKING_LEVEL", "GEMINI_THINKING_LEVEL"),
    )
    gemini_max_output_tokens: int = Field(
        default=1024,
        validation_alias=AliasChoices("ACIL_GEMINI_MAX_OUTPUT_TOKENS", "GEMINI_MAX_OUTPUT_TOKENS"),
    )
    bedrock_region: str = Field(default="ap-south-1", validation_alias="BEDROCK_REGION")
    bedrock_model: str = Field(
        default="in.moonshotai.kimi-k3", validation_alias="BEDROCK_MODEL"
    )
    bedrock_api_key: str | None = Field(default=None, validation_alias="BEDROCK_API_KEY")
    bedrock_auth_mode: str = Field(default="iam", validation_alias="BEDROCK_AUTH_MODE")
    aws_profile: str | None = Field(default=None, validation_alias="AWS_PROFILE")
    bedrock_max_output_tokens: int = Field(
        default=512, validation_alias="BEDROCK_MAX_OUTPUT_TOKENS"
    )
    kimi_chat_max_output_tokens: int = Field(
        default=2048, validation_alias="KIMI_CHAT_MAX_OUTPUT_TOKENS"
    )
    bedrock_temperature: float = Field(default=0.2, validation_alias="BEDROCK_TEMPERATURE")
    bedrock_reasoning_effort: str = Field(
        default="low", validation_alias="BEDROCK_REASONING_EFFORT"
    )
    evaluation_runner_enabled: bool = False
    evaluation_docker_image: str | None = None
    evaluation_timeout_seconds: int = 120
    model_config = SettingsConfigDict(env_prefix="ACIL_", env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
