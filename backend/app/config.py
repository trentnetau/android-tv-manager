from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    adb_path: str = "adb"
    adb_connect_timeout_sec: int = 15
    command_timeout_sec: int = 120
    # Optional HTTP basic auth (leave empty to disable)
    auth_username: str = ""
    auth_password: str = ""
    upload_dir: str = "/tmp/android-tv-uploads"


settings = Settings()
