"""
IDMC AI Assistant — FastAPI app.

Routes:
  GET  /        → redirect to /ui
  GET  /ui      → web chat UI (token gate)
  POST /connect → validate token, set httpOnly cookie, return org info
  POST /chat    → chat API (reads httpOnly cookie server-side)
  POST /disconnect → clear cookie
  GET  /health  → health check
"""

import logging
import os
from pathlib import Path

import httpx
from cryptography.fernet import Fernet
from dotenv import load_dotenv

from fastapi import FastAPI, Request, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv(Path(__file__).parent.parent / ".env")

from mcp_client import McpClient, mcp_session
from llm import chat

from token_auth import decode_token, TokenError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger("ai_assistant")

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "").rstrip("/") + "/mcp"
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "").strip()
COOKIE_NAME    = "idmc_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

app = FastAPI(title="IDMC AI Assistant")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


def _fernet() -> Fernet:
    if not ENCRYPTION_KEY:
        raise RuntimeError("ENCRYPTION_KEY is not set")
    return Fernet(ENCRYPTION_KEY.encode())

def _encrypt_for_cookie(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()

def _decrypt_from_cookie(blob: str) -> str:
    return _fernet().decrypt(blob.encode()).decode()


@app.post("/connect")
async def connect(request: Request):
    body = await request.json()
    token = body.get("token", "").strip()
    if not token:
        return JSONResponse({"error": "No token provided"}, status_code=400)

    try:
        creds = decode_token(token)
    except TokenError as e:
        return JSONResponse({"error": str(e)}, status_code=401)

    pod      = creds.get("pod", "")
    username = creds.get("username", "")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://{pod}.informaticacloud.com/identity-service/api/v1/Login",
                json={"username": username, "password": creds.get("password", "")},
                headers={"Content-Type": "application/json"},
            )
        org_name = pod
        if resp.status_code == 200:
            data = resp.json()
            org_name = data.get("orgName") or data.get("currentOrgName") or pod
    except Exception:
        org_name = pod

    try:
        cookie_blob = _encrypt_for_cookie(token)
    except Exception as e:
        return JSONResponse({"error": f"Server config error: {e}"}, status_code=500)

    response = JSONResponse({"org_name": org_name, "pod": pod, "username": username})
    response.set_cookie(
        key=COOKIE_NAME, value=cookie_blob,
        max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax", secure=False,
    )
    return response


@app.post("/disconnect")
async def disconnect():
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(COOKIE_NAME)
    return response


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []
    pod: str = ""


@app.post("/chat")
async def chat_endpoint(
    body: ChatRequest,
    request: Request,
    idmc_session: str | None = Cookie(default=None),
):
    if not idmc_session:
        return JSONResponse({"error": "Not connected. Please enter your token."}, status_code=401)

    try:
        token = _decrypt_from_cookie(idmc_session)
        creds = decode_token(token)
    except Exception:
        return JSONResponse({"error": "Session invalid or expired. Please reconnect."}, status_code=401)

    if not MCP_SERVER_URL or MCP_SERVER_URL == "/mcp":
        return JSONResponse({"error": "MCP_SERVER_URL is not configured."}, status_code=500)

    try:
        mcp = McpClient(server_url=MCP_SERVER_URL, token=token)
        async with mcp_session(MCP_SERVER_URL, token) as session:
            mcp.set_session(session)
            response, trace = await chat(
                user_message=body.message,
                mcp=mcp,
                history=body.history,
            )
        return JSONResponse({"response": response, "trace": trace})
    except Exception as e:
        logger.exception("Chat error")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/enroll")
async def enroll_redirect():
    mcp_base = MCP_SERVER_URL.replace("/mcp", "").rstrip("/")
    return Response(status_code=302, headers={"Location": f"{mcp_base}/enroll"})


@app.get("/health")
async def health():
    return {"status": "ok", "server": "official-idmc-ai-assistant"}


@app.get("/ui", response_class=HTMLResponse)
async def ui():
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse('<meta http-equiv="refresh" content="0;url=/ui">', status_code=302)
