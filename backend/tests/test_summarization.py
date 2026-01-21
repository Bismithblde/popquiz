"""Tests for the summarization service and scheduler."""
import asyncio
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from ..services.database import LectureRepository, TranscriptRecord
from ..services.summarization import SummarizationService, SummaryScheduler


@pytest.fixture
async def repo():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        repository = LectureRepository(db_path=db_path)
        await repository.initialize()
        yield repository


@pytest.fixture
def summarizer():
    """Create a mock summarizer."""
    return SummarizationService(model="gemini-1.5-flash")


class TestSummarizationService:
    @pytest.mark.asyncio
    async def test_summarize_basic(self, summarizer):
        """Test basic summarization with mock Gemini response."""
        transcripts = [
            TranscriptRecord(
                id=1,
                session_id="room1",
                start_time=0.0,
                end_time=60.0,
                text="The teacher discussed Newton's laws of motion.",
                created_at=0.0,
            ),
            TranscriptRecord(
                id=2,
                session_id="room1",
                start_time=60.0,
                end_time=120.0,
                text="We learned about gravity and acceleration.",
                created_at=60.0,
            ),
        ]

        # Mock the Gemini API call
        with patch.object(summarizer, "_summarize_blocking") as mock_api:
            mock_api.return_value = "• Newton's laws: Force = mass × acceleration\n• Gravity: F = G(m1*m2)/r²"

            result = await summarizer.summarize(transcripts)

            assert "Newton's laws" in result
            assert "Gravity" in result
            mock_api.assert_called_once()

    @pytest.mark.asyncio
    async def test_summarize_preserves_keywords(self, summarizer):
        """Test that summarization preserves technical keywords."""
        transcripts = [
            TranscriptRecord(
                id=1,
                session_id="room1",
                start_time=0.0,
                end_time=60.0,
                text="We discussed eigenvalues and diagonalization in linear algebra.",
                created_at=0.0,
            ),
        ]

        with patch.object(summarizer, "_summarize_blocking") as mock_api:
            mock_api.return_value = "• Eigenvalues and diagonalization are key concepts in linear algebra"

            result = await summarizer.summarize(transcripts)

            assert "eigenvalues" in result.lower()
            assert "diagonalization" in result.lower()

    @pytest.mark.asyncio
    async def test_summarize_empty_raises_error(self, summarizer):
        """Test that empty transcripts raise an error."""
        with pytest.raises(ValueError, match="requires at least one transcript"):
            await summarizer.summarize([])

    def test_format_segment(self):
        """Test timestamp formatting for segments."""
        record = TranscriptRecord(
            id=1,
            session_id="room1",
            start_time=330.0,  # 5:30
            end_time=340.0,    # +10 seconds
            text="Hello world",
            created_at=0.0,
        )

        segment = SummarizationService._format_segment(1, record)

        assert "05:30" in segment
        assert "(+10.0s)" in segment
        assert "Hello world" in segment

    def test_build_prompt_structure(self, summarizer):
        """Test that the prompt is structured correctly."""
        transcripts = [
            TranscriptRecord(
                id=1,
                session_id="room1",
                start_time=0.0,
                end_time=60.0,
                text="First part",
                created_at=0.0,
            ),
        ]

        prompt = summarizer._build_prompt(transcripts)

        assert isinstance(prompt, list)
        assert len(prompt) == 2
        assert "concise bullet points" in prompt[0]
        assert "First part" in prompt[1]


class TestSummaryScheduler:
    @pytest.mark.asyncio
    async def test_scheduler_triggers_summary(self, repo):
        """Test that the scheduler triggers a summary when conditions are met."""
        summarizer = SummarizationService()
        scheduler = SummaryScheduler(repo, summarizer, window_seconds=5, min_chunks=2)

        # Mock the summarizer
        summarizer.summarize = AsyncMock(return_value="• Summary point 1\n• Summary point 2")

        # Insert transcripts
        records = []
        for i in range(2):
            record = await repo.insert_transcript(
                session_id="room1",
                start_time=float(i * 2),
                end_time=float((i * 2) + 1),
                text=f"Segment {i}",
            )
            records.append(record)

        # Trigger scheduling on the second record
        await scheduler.consider_transcript(records[-1])

        # Check that a summary was created
        summaries = await repo.fetch_all_summaries("room1")
        assert len(summaries) == 1
        assert "Summary point" in summaries[0].summary_text

    @pytest.mark.asyncio
    async def test_scheduler_deduplicates(self, repo):
        """Test that the scheduler doesn't create duplicate summaries."""
        summarizer = SummarizationService()
        scheduler = SummaryScheduler(repo, summarizer, window_seconds=300, min_chunks=1)

        summarizer.summarize = AsyncMock(return_value="• Summary")

        record = await repo.insert_transcript(
            session_id="room1",
            start_time=0.0,
            end_time=60.0,
            text="First segment",
        )

        # Trigger twice quickly
        await scheduler.consider_transcript(record)
        await scheduler.consider_transcript(record)

        # Should only create one summary due to the time window check
        summaries = await repo.fetch_all_summaries("room1")
        assert len(summaries) == 1

    @pytest.mark.asyncio
    async def test_scheduler_respects_min_chunks(self, repo):
        """Test that scheduler requires minimum chunks."""
        summarizer = SummarizationService()
        scheduler = SummaryScheduler(repo, summarizer, window_seconds=300, min_chunks=3)

        summarizer.summarize = AsyncMock(return_value="• Summary")

        # Insert only 2 chunks
        for i in range(2):
            record = await repo.insert_transcript(
                session_id="room1",
                start_time=float(i * 2),
                end_time=float((i * 2) + 1),
                text=f"Segment {i}",
            )

        await scheduler.consider_transcript(record)

        # Should not create a summary
        summaries = await repo.fetch_all_summaries("room1")
        assert len(summaries) == 0

    @pytest.mark.asyncio
    async def test_scheduler_per_session(self, repo):
        """Test that scheduler maintains separate state per session."""
        summarizer = SummarizationService()
        scheduler = SummaryScheduler(repo, summarizer, window_seconds=300, min_chunks=1)

        summarizer.summarize = AsyncMock(return_value="• Summary")

        # Insert into two different sessions
        record1 = await repo.insert_transcript(
            session_id="room1",
            start_time=0.0,
            end_time=60.0,
            text="Room 1",
        )
        record2 = await repo.insert_transcript(
            session_id="room2",
            start_time=0.0,
            end_time=60.0,
            text="Room 2",
        )

        await scheduler.consider_transcript(record1)
        await scheduler.consider_transcript(record2)

        summaries1 = await repo.fetch_all_summaries("room1")
        summaries2 = await repo.fetch_all_summaries("room2")

        assert len(summaries1) == 1
        assert len(summaries2) == 1
