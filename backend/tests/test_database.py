"""Tests for the database/repository layer."""
import asyncio
import pytest
import tempfile
from pathlib import Path

from ..services.database import LectureRepository, TranscriptRecord, SummaryRecord


@pytest.fixture
async def repo():
    """Create a temporary in-memory database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        repository = LectureRepository(db_path=db_path)
        await repository.initialize()
        yield repository


@pytest.mark.asyncio
async def test_insert_transcript(repo):
    """Test inserting a transcript record."""
    record = await repo.insert_transcript(
        session_id="room1",
        start_time=0.0,
        end_time=10.0,
        text="Hello world",
    )
    assert record.session_id == "room1"
    assert record.text == "Hello world"
    assert record.id is not None


@pytest.mark.asyncio
async def test_fetch_transcripts_in_window(repo):
    """Test fetching transcripts by time window."""
    await repo.insert_transcript(
        session_id="room1",
        start_time=0.0,
        end_time=5.0,
        text="First segment",
    )
    await repo.insert_transcript(
        session_id="room1",
        start_time=5.0,
        end_time=10.0,
        text="Second segment",
    )
    await repo.insert_transcript(
        session_id="room2",
        start_time=0.0,
        end_time=5.0,
        text="Different room",
    )

    # Fetch transcripts from room1 between 0-10
    records = await repo.fetch_transcripts_in_window(
        session_id="room1",
        start_time=0.0,
        end_time=10.0,
    )
    assert len(records) == 2
    assert records[0].text == "First segment"
    assert records[1].text == "Second segment"


@pytest.mark.asyncio
async def test_fetch_transcripts_since(repo):
    """Test fetching transcripts from a minimum start time."""
    await repo.insert_transcript(
        session_id="room1",
        start_time=0.0,
        end_time=5.0,
        text="Old segment",
    )
    await repo.insert_transcript(
        session_id="room1",
        start_time=10.0,
        end_time=15.0,
        text="Recent segment",
    )

    records = await repo.fetch_transcripts_since(
        session_id="room1",
        min_start_time=8.0,
    )
    assert len(records) == 1
    assert records[0].text == "Recent segment"


@pytest.mark.asyncio
async def test_insert_summary(repo):
    """Test inserting a summary record."""
    summary = await repo.insert_summary(
        session_id="room1",
        start_time=0.0,
        end_time=300.0,
        summary_text="• Main idea\n• Key point",
    )
    assert summary.session_id == "room1"
    assert summary.id is not None
    assert "Main idea" in summary.summary_text


@pytest.mark.asyncio
async def test_fetch_all_summaries(repo):
    """Test fetching all summaries for a session."""
    await repo.insert_summary(
        session_id="room1",
        start_time=0.0,
        end_time=300.0,
        summary_text="First summary",
    )
    await repo.insert_summary(
        session_id="room1",
        start_time=300.0,
        end_time=600.0,
        summary_text="Second summary",
    )
    await repo.insert_summary(
        session_id="room2",
        start_time=0.0,
        end_time=300.0,
        summary_text="Different room",
    )

    summaries = await repo.fetch_all_summaries("room1")
    assert len(summaries) == 2
    assert summaries[0].summary_text == "First summary"


@pytest.mark.asyncio
async def test_fetch_latest_summary_time(repo):
    """Test fetching the latest summary timestamp."""
    latest = await repo.fetch_latest_summary_time("room1")
    assert latest == 0.0

    await repo.insert_summary(
        session_id="room1",
        start_time=0.0,
        end_time=100.0,
        summary_text="First",
    )
    latest = await repo.fetch_latest_summary_time("room1")
    assert latest == 100.0

    await repo.insert_summary(
        session_id="room1",
        start_time=100.0,
        end_time=200.0,
        summary_text="Second",
    )
    latest = await repo.fetch_latest_summary_time("room1")
    assert latest == 200.0


@pytest.mark.asyncio
async def test_session_isolation(repo):
    """Test that queries are properly isolated by session_id."""
    await repo.insert_transcript(
        session_id="room1",
        start_time=0.0,
        end_time=10.0,
        text="Room 1 text",
    )
    await repo.insert_transcript(
        session_id="room2",
        start_time=0.0,
        end_time=10.0,
        text="Room 2 text",
    )

    room1_records = await repo.fetch_transcripts_in_window(
        session_id="room1",
        start_time=0.0,
        end_time=20.0,
    )
    room2_records = await repo.fetch_transcripts_in_window(
        session_id="room2",
        start_time=0.0,
        end_time=20.0,
    )

    assert len(room1_records) == 1
    assert room1_records[0].text == "Room 1 text"
    assert len(room2_records) == 1
    assert room2_records[0].text == "Room 2 text"
