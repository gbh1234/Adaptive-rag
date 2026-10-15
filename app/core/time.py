"""UTC time helpers."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """All persisted timestamps are UTC. Presentation layer converts timezone."""
    return datetime.now(UTC)
