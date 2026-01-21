from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Dict, List

from fastapi import (
    Body,
    FastAPI,
    File,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, Field

from .services.audio_processor import AudioChunk, AudioProcessor
from .services.context import ContextBuilder
from .services.database import LectureRepository
from .services.quiz import QuizService
from .services.summarization import SummarizationService, SummaryScheduler
from .services.transcription import TranscriptionService
from .services.webhook_manager import ConnectionManager


manager = ConnectionManager()
audio_queue: asyncio.Queue = asyncio.Queue()
repository = LectureRepository()
transcription_service = TranscriptionService()
summarization_service = SummarizationService()
summary_scheduler = SummaryScheduler(repository, summarization_service)
audio_processor = AudioProcessor(
    audio_queue,
    transcription_service=transcription_service,
    repository=repository,
    summary_scheduler=summary_scheduler,
)
context_builder = ContextBuilder(repository)
quiz_service = QuizService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle: startup and shutdown."""
    # Startup
    await repository.initialize()
    asyncio.create_task(audio_processor.run_forever())
    yield
    # Shutdown
    pass


app = FastAPI(lifespan=lifespan)


class QuizTriggerRequest(BaseModel):
    question_count: int = Field(3, ge=1, le=10)
    recent_minutes: int = Field(10, ge=1, le=30)


@app.get("/health_check")
async def health_check() -> dict:
    return {"status": "online"}


@app.post("/rooms/{room_id}/audio")
async def ingest_audio(room_id: str, file: UploadFile = File(...)) -> dict:
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Audio payload is empty")
    chunk = AudioChunk(session_id=room_id, payload=payload)
    await audio_queue.put(chunk)
    return {"status": "queued", "bytes": len(payload)}


@app.post("/rooms/{room_id}/quiz")
async def trigger_quiz(room_id: str, request: QuizTriggerRequest = Body(...)) -> dict:
    await audio_processor.force_flush(room_id)
    context_package = await context_builder.build(room_id, request.recent_minutes)
    if not context_package.has_content:
        raise HTTPException(status_code=400, detail="No transcripts available yet")

    questions = await quiz_service.generate_questions(
        context_package, question_count=request.question_count
    )
    await manager.broadcast_to_room(room_id, {"type": "quiz", "questions": questions})
    return {"questions": questions}


@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str) -> None:
    await manager.connect(websocket, room_id)
    try:
        while True:
            data = await websocket.receive_text()
            message = {"message": f"Room {room_id} says: {data}"}
            await manager.broadcast_to_room(room_id, message)
    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)


