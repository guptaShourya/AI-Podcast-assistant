import enum
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class EpisodeStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"


class Podcast(Base):
    __tablename__ = "podcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    rss_url: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    episodes: Mapped[list["Episode"]] = relationship(
        back_populates="podcast", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Podcast id={self.id} name={self.name!r}>"


class Episode(Base):
    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    podcast_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("podcasts.id", ondelete="CASCADE"), nullable=False
    )
    guid: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    audio_url: Mapped[str] = mapped_column(String, nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[EpisodeStatus] = mapped_column(
        Enum(EpisodeStatus), default=EpisodeStatus.pending, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    podcast: Mapped["Podcast"] = relationship(back_populates="episodes")
    summary: Mapped["Summary | None"] = relationship(
        back_populates="episode", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Episode id={self.id} title={self.title!r} status={self.status}>"


class Summary(Base):
    __tablename__ = "summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    transcript_text: Mapped[str] = mapped_column(Text, nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    key_topics: Mapped[list] = mapped_column(JSON, nullable=False)
    highlights: Mapped[list] = mapped_column(JSON, nullable=False)
    listen_score: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    episode: Mapped["Episode"] = relationship(back_populates="summary")

    def __repr__(self) -> str:
        return f"<Summary id={self.id} episode_id={self.episode_id} score={self.listen_score}>"
