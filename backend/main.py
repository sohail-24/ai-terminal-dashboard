from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
import os
import pty
import fcntl
import asyncio
import signal
import json

app = FastAPI()


@app.get("/")
async def home():
    frontend_path = os.path.abspath("../frontend/index.html")
    return FileResponse(frontend_path)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    # Start a real PTY shell
    pid, fd = pty.fork()

    if pid == 0:
        # Child process → run bash shell
        os.execvp("/bin/bash", ["/bin/bash"])

    # Parent process → make PTY non-blocking
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

    async def read_pty():
        while True:
            try:
                await asyncio.sleep(0.02)
                data = os.read(fd, 4096).decode(errors="ignore")

                if data:
                    await websocket.send_text(json.dumps({
                        "type": "output",
                        "message": data
                    }))

            except BlockingIOError:
                continue
            except OSError:
                break

    reader_task = asyncio.create_task(read_pty())

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                payload = json.loads(raw)
                action = payload.get("action")
            except Exception:
                payload = {"action": "input", "data": raw}
                action = "input"

            # -----------------------------
            # TERMINAL INPUT (raw keystrokes)
            # -----------------------------
            if action == "input":
                data = payload.get("data", "")
                if data:
                    os.write(fd, data.encode())

            # -----------------------------
            # STOP CURRENT COMMAND (Ctrl+C)
            # -----------------------------
            elif action == "stop":
                try:
                    os.kill(pid, signal.SIGINT)

                    await websocket.send_text(json.dumps({
                        "type": "system",
                        "message": "\r\n[STOPPED BY USER]\r\n"
                    }))

                except ProcessLookupError:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": "\r\n[ERROR] Shell process not found\r\n"
                    }))

    except WebSocketDisconnect:
        reader_task.cancel()
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
