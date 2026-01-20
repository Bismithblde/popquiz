from fastapi import WebSocket
from typing import Dict, List

class ConnectionManager:
    """
    Manages active WebSocket connections organized by classroom rooms.

    This service handles the lifecycle of WebSocket connections, allowing
    for real-time communication between teachers and students. It maintains
    an in-memory mapping of room IDs to their respective active participants.

    Attributes:
        active_connections (Dict[str, List[WebSocket]]): A dictionary where 
            keys are room unique identifiers and values are lists of 
            active WebSocket objects in that room.
    """

    def __init__(self):
        """Initializes an empty dictionary to track classroom connections."""
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, room_id: str):
        """
        Accepts a new WebSocket connection and assigns it to a specific room.

        Args:
            websocket (WebSocket): The incoming FastAPI WebSocket connection.
            room_id (str): The unique ID of the classroom/session.
        """
        await websocket.accept()
        if room_id not in self.active_connections:
            self.active_connections[room_id] = []
        self.active_connections[room_id].append(websocket)

    def disconnect(self, websocket: WebSocket, room_id: str):
        """
        Removes a closed WebSocket connection from the room tracking.

        If a room becomes empty after a disconnection, the room key is 
        deleted from the dictionary to optimize memory usage.

        Args:
            websocket (WebSocket): The WebSocket connection to remove.
            room_id (str): The ID of the room the user is leaving.
        """
        if room_id in self.active_connections:
            self.active_connections[room_id].remove(websocket)
            if not self.active_connections[room_id]:
                # garbage collection
                del self.active_connections[room_id]

    async def broadcast_to_room(self, room_id: str, message: dict):
        """
        Sends a JSON message to all active participants in a specific room.

        Args:
            room_id (str): The target classroom ID.
            message (dict): The data payload (e.g., quiz questions) to send.
        """
        if room_id in self.active_connections:
            for connection in self.active_connections[room_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass