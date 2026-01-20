from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Dict, List

app = FastAPI()

# Store active WebSocket connections by room
rooms: Dict[str, List[WebSocket]] = {}

@app.get("/health_check")
def health_check():
    return {"status": "online"}

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await websocket.accept()
    
    # Add connection to room
    if room_id not in rooms:
        rooms[room_id] = []
    rooms[room_id].append(websocket)
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            
            # Broadcast to all clients in the same room
            message = {"message": f"Room {room_id} says: {data}"}
            for connection in rooms[room_id]:
                await connection.send_json(message)
    
    except WebSocketDisconnect:
        # Remove connection from room
        rooms[room_id].remove(websocket)
        if not rooms[room_id]:
            del rooms[room_id]

