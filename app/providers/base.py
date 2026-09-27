from dataclasses import dataclass


@dataclass
class Usage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class ProviderError(Exception):
    """Raised on any failed/invalid AI call. retryable=False for things a retry won't fix (e.g. bad key)."""
    def __init__(self, msg: str, retryable: bool = True):
        super().__init__(msg)
        self.retryable = retryable
