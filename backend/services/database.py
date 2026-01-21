from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import aiosqlite


@dataclass(slots=True)
class TranscriptRecord:
    id: int
    session_id: str
    start_time: float
    end_time: float
    text: str
    created_at: float


@dataclass(slots=True)
class SummaryRecord:
    id: int
    session_id: str
    start_time: float
    end_time: float
    summary_text: str
    created_at: float


class LectureRepository:
    """Persistent store for transcripts and rolling summaries."""

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        base_path = Path(__file__).resolve().parents[1]
        default_path = base_path / "data" / "popquiz.db"
        self.db_path = Path(db_path) if db_path else default_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            conn = await self._connect()
            try:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS transcripts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        start_time REAL NOT NULL,
                        end_time REAL NOT NULL,
                        text TEXT NOT NULL,
                        created_at REAL NOT NULL
                    )
                    """
                )
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS summaries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        start_time REAL NOT NULL,
                        end_time REAL NOT NULL,
                        summary_text TEXT NOT NULL,
                        created_at REAL NOT NULL
                    )
                    """
                )
                await conn.commit()
            finally:
                await conn.close()

            self._initialized = True

    async def insert_transcript(
        self, *, session_id: str, start_time: float, end_time: float, text: str
    ) -> TranscriptRecord:
        created_at = time.time()
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                """
                INSERT INTO transcripts (session_id, start_time, end_time, text, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, start_time, end_time, text, created_at),
            )
            await conn.commit()
            record_id = cursor.lastrowid
            await cursor.close()
        finally:
            await conn.close()

        return TranscriptRecord(
            id=record_id,
            session_id=session_id,
            start_time=start_time,
            end_time=end_time,
            text=text,
            created_at=created_at,
        )

    async def insert_summary(
        self, *, session_id: str, start_time: float, end_time: float, summary_text: str
    ) -> SummaryRecord:
        created_at = time.time()
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                """
                INSERT INTO summaries (session_id, start_time, end_time, summary_text, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, start_time, end_time, summary_text, created_at),
            )
            await conn.commit()
            record_id = cursor.lastrowid
            await cursor.close()
        finally:
            await conn.close()

        return SummaryRecord(
            id=record_id,
            session_id=session_id,
            start_time=start_time,
            end_time=end_time,
            summary_text=summary_text,
            created_at=created_at,
        )

    async def fetch_transcripts_in_window(
        self, *, session_id: str, start_time: float, end_time: float
    ) -> List[TranscriptRecord]:
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                """
                SELECT id, session_id, start_time, end_time, text, created_at
                FROM transcripts
                WHERE session_id = ? AND end_time >= ? AND start_time <= ?
                ORDER BY start_time ASC
                """,
                (session_id, start_time, end_time),
            )
            rows = await cursor.fetchall()
            await cursor.close()
        finally:
            await conn.close()

        return [self._row_to_transcript(row) for row in rows]

    async def fetch_transcripts_since(
        self, *, session_id: str, min_start_time: float
    ) -> List[TranscriptRecord]:
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                """
                SELECT id, session_id, start_time, end_time, text, created_at
                FROM transcripts
                WHERE session_id = ? AND end_time >= ?
                ORDER BY start_time ASC
                """,
                (session_id, min_start_time),
            )
            rows = await cursor.fetchall()
            await cursor.close()
        finally:
            await conn.close()

        return [self._row_to_transcript(row) for row in rows]

    async def fetch_all_summaries(self, session_id: str) -> List[SummaryRecord]:
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                """
                SELECT id, session_id, start_time, end_time, summary_text, created_at
                FROM summaries
                WHERE session_id = ?
                ORDER BY start_time ASC
                """,
                (session_id,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
        finally:
            await conn.close()

        return [self._row_to_summary(row) for row in rows]

    async def fetch_latest_summary_time(self, session_id: str) -> float:
        conn = await self._connect()
        try:
            cursor = await conn.execute(
                """
                SELECT MAX(end_time) as latest
                FROM summaries
                WHERE session_id = ?
                """,
                (session_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
        finally:
            await conn.close()

        return float(row[0]) if row and row[0] is not None else 0.0

    async def _connect(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self.db_path.as_posix())
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    @staticmethod
    def _row_to_transcript(row: aiosqlite.Row) -> TranscriptRecord:
        return TranscriptRecord(
            id=row[0],
            session_id=row[1],
            start_time=row[2],
            end_time=row[3],
            text=row[4],
            created_at=row[5],
        )

    @staticmethod
    def _row_to_summary(row: aiosqlite.Row) -> SummaryRecord:
        return SummaryRecord(
            id=row[0],
            session_id=row[1],
            start_time=row[2],
            end_time=row[3],
            summary_text=row[4],
            created_at=row[5],
        )
