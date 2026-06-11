from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.api.websockets.manager import ws_manager
from app.services.auth import decode_token

router = APIRouter()


@router.websocket("/ws/auctions/{auction_id}")
async def auction_websocket(
    auction_id: str,
    websocket: WebSocket,
    token: str = Query(...),           # pass JWT as ?token=... query param
):
    # Authenticate the WebSocket connection
    try:
        decode_token(token)
    except ValueError:
        await websocket.close(code=4001)
        return

    await ws_manager.connect(auction_id, websocket)
    try:
        # Keep connection alive; clients can send ping frames
        while True:
            data = await websocket.receive_text()
            # Echo heartbeat or handle client-sent events
            if data == "ping":
                await ws_manager.send_to_connection(websocket, {"event": "pong"})
    except WebSocketDisconnect:
        await ws_manager.disconnect(auction_id, websocket)