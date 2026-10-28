from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

class Settings(BaseSettings):
    DEEPSEEK_API_KEY: str  # 需要加载的环境变量
    DEEPSEEK_URL: str
    MAIL_USERNAME: str
    MAIL_PASSWORD: str
    MAIL_PORT: int
    MAIL_SERVER: str
    MAIL_FROM: str
    DATABASE_URL: str
    MOMERY_DATABASE_URL: str
    REDIS_URL: str
    OLLAMA_URL: str
    MASTER_KEY: str
    SECRET_KEY: str
    ALGORITHM: str
    JWT_SECRET: str
    JWT_ALGORITHM : str
    ACCESS_TOKEN_EXPIRE_MINUTES: int  # 7天接入令牌过期
    REFRESH_TOKEN_EXPIRE_DAYS: int       # 14天刷新令牌过期
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", extra="ignore"
    )  # 关于如何加载数据的元配置

config = Settings()  # 全局单例，配置实例
