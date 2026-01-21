from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List

from .database import LectureRepository, SummaryRecord, TranscriptRecord


@dataclass(slots=True)
class ContextPackage:
    session_id: str
    global_summaries: List[SummaryRecord]
    recent_transcripts: List[TranscriptRecord]

    @property
    def has_content(self) -> bool:
        return bool(self.global_summaries or self.recent_transcripts)

    def render_summary_block(self) -> str:
        if not self.global_summaries:
            return "No summaries captured yet."
        lines = []
        for summary in self.global_summaries:
            lines.append(
                f"[{summary.start_time:0.0f}-{summary.end_time:0.0f}] {summary.summary_text.strip()}"
            )
        return "\n".join(lines)

    def render_recent_block(self) -> str:
        if not self.recent_transcripts:
            return "No recent transcripts available."
        return "\n\n".join(record.text.strip() for record in self.recent_transcripts)


class ContextBuilder:
    def __init__(self, repository: LectureRepository, *, default_recent_minutes: int = 10) -> None:
        self.repository = repository
        self.default_recent_minutes = default_recent_minutes

    async def build(self, session_id: str, recent_minutes: int | None = None) -> ContextPackage:
        window_minutes = recent_minutes or self.default_recent_minutes
        cutoff = time.time() - (window_minutes * 60)
        summaries = await self.repository.fetch_all_summaries(session_id)
        recent = await self.repository.fetch_transcripts_since(
            session_id=session_id, min_start_time=cutoff
        )
        return ContextPackage(
            session_id=session_id,
            global_summaries=summaries,
            recent_transcripts=recent,
        )
