"""Pydantic schemas: the contract for AI output and for the HTTP boundary."""
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator

Category = Literal["animal", "plant", "food", "landscape", "person", "object", "other"]


class ImageTags(BaseModel):
    """Structured vision output. Every model response is validated against this before it is trusted."""
    subject: str = Field(min_length=2, max_length=60, description="common name of the main subject, e.g. 'red fox'")
    category: Category
    attributes: list[str] = Field(min_length=1, max_length=8)
    caption: str = Field(min_length=8, max_length=300)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("subject")
    @classmethod
    def lower_subject(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("attributes")
    @classmethod
    def clean_attrs(cls, v: list[str]) -> list[str]:
        v = [a.strip().lower() for a in v if a and a.strip()]
        if not v:
            raise ValueError("attributes must not be empty")
        return v


class PostTopic(BaseModel):
    """What a post is about, extracted by the text model (validated the same way)."""
    subject: str = Field(min_length=2, max_length=60)
    category: Category
    keywords: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("subject")
    @classmethod
    def lower_subject(cls, v: str) -> str:
        return v.strip().lower()


# ---- HTTP request/response models ----
class PostIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=20, max_length=20000)
    slug: Optional[str] = Field(default=None, pattern=r"^[a-z0-9-]{3,80}$")


class IngestIn(BaseModel):
    force: bool = False          # re-process images that are already tagged
    limit: Optional[int] = Field(default=None, ge=1, le=500)


class ReviewIn(BaseModel):
    decision: Literal["approve", "reject"]
    reviewer: str = Field(min_length=2, max_length=80)
    note: Optional[str] = Field(default=None, max_length=500)
