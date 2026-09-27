"""Data layer: SQLAlchemy models. Tables are created by app/migrations.py (versioned)."""
from datetime import datetime, timezone
from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from .config import settings


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Image(Base):
    __tablename__ = "images"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(40), default="demo")
    filename: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    license: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")   # pending|tagged|flagged|failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    tags: Mapped["ImageTag | None"] = relationship(back_populates="image", uselist=False, cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("tenant_id", "sha256", name="uq_image_tenant_sha"),
                      Index("ix_images_tenant_status", "tenant_id", "status"))


class ImageTag(Base):
    __tablename__ = "image_tags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), unique=True)
    subject: Mapped[str] = mapped_column(String(60))
    category: Mapped[str] = mapped_column(String(20))
    attributes: Mapped[list] = mapped_column(JSON)
    caption: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    flag_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    model: Mapped[str] = mapped_column(String(60))
    image: Mapped[Image] = relationship(back_populates="tags")
    __table_args__ = (Index("ix_image_tags_subject", "subject"), Index("ix_image_tags_category", "category"))


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(40), default="demo")
    slug: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(String(60), nullable=True)
    category: Mapped[str | None] = mapped_column(String(20), nullable=True)
    keywords: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|ready|failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_post_tenant_slug"),)


class Embedding(Base):
    """One vector per owner. JSON array storage is fine at ~50 images (pgvector is a stretch goal)."""
    __tablename__ = "embeddings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_type: Mapped[str] = mapped_column(String(10))     # image | post | subject
    owner_key: Mapped[str] = mapped_column(String(120))      # image id, post id, or subject text
    model: Mapped[str] = mapped_column(String(60))
    text: Mapped[str] = mapped_column(Text)
    vector: Mapped[list] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("owner_type", "owner_key", "model", name="uq_embedding_owner"),
                      Index("ix_embeddings_owner", "owner_type", "owner_key"))


class Suggestion(Base):
    __tablename__ = "suggestions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"))
    rank: Mapped[int] = mapped_column(Integer)
    similarity: Mapped[float] = mapped_column(Float)
    verdict: Mapped[str] = mapped_column(String(10))        # accepted | rejected
    reasons: Mapped[list] = mapped_column(JSON)
    review_status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|approved|rejected
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("post_id", "image_id", name="uq_suggestion_pair"),
                      Index("ix_suggestions_post_rank", "post_id", "rank"))


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    suggestion_id: Mapped[int] = mapped_column(ForeignKey("suggestions.id", ondelete="CASCADE"))
    decision: Mapped[str] = mapped_column(String(10))
    reviewer: Mapped[str] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_reviews_suggestion", "suggestion_id"),)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(40), default="demo")
    kind: Mapped[str] = mapped_column(String(30))
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|done|failed|budget_stopped
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    flagged: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("tenant_id", "kind", "idempotency_key", name="uq_job_idem"),)


class CostLog(Base):
    __tablename__ = "cost_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))          # vision | embedding | text
    model: Mapped[str] = mapped_column(String(60))
    target: Mapped[str] = mapped_column(String(120))       # e.g. image:12, post:3
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    est_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_cost_job", "job_id"), Index("ix_cost_created", "created_at"))


engine = create_engine(settings.database_url, future=True,
                       connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
