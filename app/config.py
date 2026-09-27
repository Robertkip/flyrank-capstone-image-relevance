"""All configuration comes from environment variables (see .env.example). Never hard-code secrets."""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")
    ai_provider: str = os.getenv("AI_PROVIDER", "gemini")          # gemini | mock
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    vision_model: str = os.getenv("VISION_MODEL", "gemini-2.5-flash")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
    images_dir: str = os.getenv("IMAGES_DIR", "./data/images")
    # Guard thresholds (tuned with scripts/eval.py - see README)
    min_confidence: float = _f("MIN_CONFIDENCE", 0.60)
    similarity_threshold: float = _f("SIMILARITY_THRESHOLD", 0.62)
    subject_similarity: float = _f("SUBJECT_SIMILARITY", 0.85)
    # Cost tracking: list prices per 1M tokens, used to estimate cost even on the free tier
    vision_input_usd_per_m: float = _f("VISION_INPUT_USD_PER_M", 0.30)
    vision_output_usd_per_m: float = _f("VISION_OUTPUT_USD_PER_M", 2.50)
    embed_input_usd_per_m: float = _f("EMBED_INPUT_USD_PER_M", 0.15)
    budget_usd: float = _f("AI_BUDGET_USD", 1.00)                   # budget guard: jobs stop above this
    max_retries: int = int(os.getenv("MAX_RETRIES", 3))


settings = Settings()
