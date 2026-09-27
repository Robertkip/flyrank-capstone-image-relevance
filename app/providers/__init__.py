from ..config import settings


def get_provider():
    if settings.ai_provider == "mock":
        from .mock import MockProvider
        return MockProvider()
    from .gemini import GeminiProvider
    return GeminiProvider()
