"""Tests for the context builder and quiz service."""
import asyncio
import json
import time
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from ..services.context import ContextBuilder, ContextPackage
from ..services.database import LectureRepository
from ..services.quiz import QuizService


@pytest.fixture
async def repo():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        repository = LectureRepository(db_path=db_path)
        await repository.initialize()
        yield repository


class TestContextBuilder:
    @pytest.mark.asyncio
    async def test_build_empty_context(self, repo):
        """Test building context when no data exists."""
        builder = ContextBuilder(repo)
        context = await builder.build("room1")

        assert context.session_id == "room1"
        assert len(context.global_summaries) == 0
        assert len(context.recent_transcripts) == 0
        assert not context.has_content

    @pytest.mark.asyncio
    async def test_build_with_summaries(self, repo):
        """Test building context with summaries."""
        builder = ContextBuilder(repo)

        await repo.insert_summary(
            session_id="room1",
            start_time=0.0,
            end_time=300.0,
            summary_text="• First concept\n• Second concept",
        )

        context = await builder.build("room1")

        assert len(context.global_summaries) == 1
        assert context.has_content

    @pytest.mark.asyncio
    async def test_build_with_recent_transcripts(self, repo):
        """Test building context with recent transcripts."""
        import time

        builder = ContextBuilder(repo, default_recent_minutes=1)

        current_time = time.time()
        recent_time = current_time - 30  # 30 seconds ago

        await repo.insert_transcript(
            session_id="room1",
            start_time=recent_time,
            end_time=recent_time + 10,
            text="Recent content",
        )
        await repo.insert_transcript(
            session_id="room1",
            start_time=recent_time - 3600,  # 1 hour ago
            end_time=recent_time - 3590,
            text="Old content",
        )

        context = await builder.build("room1", recent_minutes=1)

        assert len(context.recent_transcripts) == 1
        assert context.recent_transcripts[0].text == "Recent content"

    @pytest.mark.asyncio
    async def test_render_summary_block(self, repo):
        """Test rendering summaries as text."""
        builder = ContextBuilder(repo)

        await repo.insert_summary(
            session_id="room1",
            start_time=0.0,
            end_time=300.0,
            summary_text="• Key point 1\n• Key point 2",
        )

        context = await builder.build("room1")
        block = context.render_summary_block()

        assert "Key point 1" in block
        assert "Key point 2" in block

    @pytest.mark.asyncio
    async def test_render_summary_block_empty(self, repo):
        """Test rendering empty summaries."""
        builder = ContextBuilder(repo)
        context = await builder.build("room1")
        block = context.render_summary_block()

        assert "No summaries" in block

    @pytest.mark.asyncio
    async def test_render_recent_block(self, repo):
        """Test rendering recent transcripts as text."""
        builder = ContextBuilder(repo)
        now = time.time()

        await repo.insert_transcript(
            session_id="room1",
            start_time=now - 20.0,
            end_time=now - 10.0,
            text="First transcript",
        )
        await repo.insert_transcript(
            session_id="room1",
            start_time=now - 10.0,
            end_time=now,
            text="Second transcript",
        )

        context = await builder.build("room1", recent_minutes=30)
        block = context.render_recent_block()

        assert "First transcript" in block
        assert "Second transcript" in block

    @pytest.mark.asyncio
    async def test_render_recent_block_empty(self, repo):
        """Test rendering empty recent transcripts."""
        builder = ContextBuilder(repo)
        context = await builder.build("room1")
        block = context.render_recent_block()

        assert "No recent transcripts" in block


class TestQuizService:
    @pytest.mark.asyncio
    async def test_generate_questions_basic(self, repo):
        """Test basic quiz generation."""
        now = time.time()
        await repo.insert_transcript(
            session_id="room1",
            start_time=now - 120.0,
            end_time=now - 60.0,
            text="The capital of France is Paris.",
        )

        builder = ContextBuilder(repo)
        context = await builder.build("room1", recent_minutes=30)

        quiz_service = QuizService()

        # Mock the Gemini API
        mock_response = [
            {
                "question": "What is the capital of France?",
                "options": ["London", "Paris", "Berlin", "Madrid"],
                "answer_index": 1,
                "rationale": "Paris is the capital of France.",
            }
        ]

        with patch.object(quiz_service, "_generate_blocking") as mock_gen:
            mock_gen.return_value = json.dumps(mock_response)

            questions = await quiz_service.generate_questions(context)

            assert len(questions) == 1
            assert questions[0]["question"] == "What is the capital of France?"
            assert questions[0]["answer_index"] == 1

    @pytest.mark.asyncio
    async def test_generate_questions_empty_context(self, repo):
        """Test that empty context raises an error."""
        builder = ContextBuilder(repo)
        context = await builder.build("room1")  # Empty context

        quiz_service = QuizService()

        with pytest.raises(ValueError, match="No context available"):
            await quiz_service.generate_questions(context)

    @pytest.mark.asyncio
    async def test_generate_questions_custom_count(self, repo):
        """Test generating custom number of questions."""
        now = time.time()
        await repo.insert_transcript(
            session_id="room1",
            start_time=now - 90.0,
            end_time=now - 30.0,
            text="Test content",
        )

        builder = ContextBuilder(repo)
        context = await builder.build("room1", recent_minutes=30)

        quiz_service = QuizService()

        questions = [
            {
                "question": f"Question {i}?",
                "options": ["A", "B", "C", "D"],
                "answer_index": 0,
            }
            for i in range(5)
        ]

        with patch.object(quiz_service, "_generate_blocking") as mock_gen:
            mock_gen.return_value = json.dumps(questions)

            result = await quiz_service.generate_questions(context, question_count=5)

            assert len(result) == 5

    @pytest.mark.asyncio
    async def test_parse_json_valid(self):
        """Test parsing valid JSON response."""
        quiz_service = QuizService()

        raw = json.dumps(
            [
                {
                    "question": "Test?",
                    "options": ["A", "B"],
                    "answer_index": 0,
                }
            ]
        )

        result = quiz_service._parse_json(raw)

        assert len(result) == 1
        assert result[0]["question"] == "Test?"

    @pytest.mark.asyncio
    async def test_parse_json_invalid(self):
        """Test parsing invalid JSON raises error."""
        quiz_service = QuizService()

        with pytest.raises(RuntimeError, match="malformed JSON"):
            quiz_service._parse_json("not valid json")

    @pytest.mark.asyncio
    async def test_parse_json_not_list(self):
        """Test parsing non-list JSON raises error."""
        quiz_service = QuizService()

        with pytest.raises(RuntimeError, match="must be a list"):
            quiz_service._parse_json('{"question": "Test?"}')

    def test_build_prompt_weighting(self, repo):
        """Test that prompt emphasizes recency."""
        quiz_service = QuizService()

        # Create a mock context
        context = MagicMock(spec=ContextPackage)
        context.render_recent_block.return_value = "Recent content"
        context.render_summary_block.return_value = "Summary content"

        prompt = quiz_service._build_prompt(context, 3)

        # Recent should appear with higher priority
        assert "highest priority" in prompt.lower()
        assert "Recent content" in prompt
        assert "Summary content" in prompt
