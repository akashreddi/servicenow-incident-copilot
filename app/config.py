"""Application configuration via Pydantic Settings (12-factor, .env driven)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- ServiceNow ---
    snow_instance_url: str = "https://devXXXXX.service-now.com"
    snow_oauth_client_id: str = ""
    snow_oauth_client_secret: str = ""
    snow_username: str = ""  # for password grant on PDI; use client_credentials in prod
    snow_password: str = ""
    snow_oauth_grant_type: str = "password"  # "password" (PDI) | "client_credentials"

    # --- Azure OpenAI (falls back to standard OpenAI if endpoint empty) ---
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_chat_deployment: str = "gpt-4o-mini"
    azure_openai_embedding_deployment: str = "text-embedding-3-small"
    openai_api_key: str = ""  # fallback

    # --- Vector store ---
    chroma_host: str = ""  # empty = embedded/local persistent client
    chroma_persist_dir: str = "./data/chroma"
    kb_collection: str = "company_kb"
    incident_collection: str = "past_incidents"

    # --- Routing ---
    routing_confidence_threshold: float = 0.7
    fallback_assignment_group: str = "L1 Service Desk"

    # --- Webhook auth (shared secret set in the ServiceNow outbound REST message) ---
    webhook_shared_secret: str = "change-me"

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
