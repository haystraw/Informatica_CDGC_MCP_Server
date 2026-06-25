"""
Informatica session management for official IDMC MCP Server.

Sessions are cached in-process, keyed by a hash of (pod, username, password).
SESSION_TIMEOUT_MINUTES controls how long a session is reused before re-auth.

Credentials come from one of two sources (checked in order):
  1. request_credentials context var — set per-request from X-IDMC-Token header
  2. .env file on disk — used for local development
"""

import hashlib
import os
import threading
from contextvars import ContextVar
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

request_credentials: ContextVar[Optional[dict]] = ContextVar(
    "request_credentials", default=None
)

_SESSION_TIMEOUT_MINUTES: Optional[int] = None


def _get_timeout_minutes() -> int:
    global _SESSION_TIMEOUT_MINUTES
    if _SESSION_TIMEOUT_MINUTES is None:
        try:
            _SESSION_TIMEOUT_MINUTES = int(os.environ.get("SESSION_TIMEOUT_MINUTES", "20"))
        except ValueError:
            _SESSION_TIMEOUT_MINUTES = 20
    return _SESSION_TIMEOUT_MINUTES


class AuthError(Exception):
    pass


class InformaticaSession:
    """
    Manages authentication state for Informatica APIs.

    URL layout derived from 'pod':
      Login URL:    https://{pod}.informaticacloud.com
      serverUrl:    returned by login (e.g. https://usw3.dm-us.informaticacloud.com/saas)
      pod_location: first label of serverUrl hostname (e.g. "usw3")
    """

    def __init__(self, pod: str, username: str, password: str):
        self.pod = pod
        self.username = username
        self.password = password
        self.login_url = f"https://{pod}.informaticacloud.com"

        self._session_id: Optional[str] = None
        self._org_id: Optional[str] = None
        self._server_url: Optional[str] = None
        self._pod_location: Optional[str] = None

    def login(self) -> None:
        resp = requests.post(
            f"{self.login_url}/ma/api/v2/user/login",
            json={"username": self.username, "password": self.password},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        if resp.status_code != 200:
            raise AuthError(f"Login failed {resp.status_code}: {resp.text}")

        data = resp.json()
        self._session_id = data.get("icSessionId")
        self._org_id = data.get("orgUuid")
        self._server_url = data.get("serverUrl", "")

        if not self._session_id or not self._org_id:
            raise AuthError("Login response missing icSessionId or orgUuid")

        # Extract pod_location from serverUrl
        # e.g. https://usw3.dm-us.informaticacloud.com/saas → "usw3"
        if self._server_url:
            host = self._server_url.replace("https://", "").split("/")[0]
            self._pod_location = host.split(".")[0]

    @property
    def session_id(self) -> str:
        if not self._session_id:
            self.login()
        return self._session_id

    @property
    def org_id(self) -> str:
        if not self._org_id:
            self.login()
        return self._org_id

    @property
    def pod_location(self) -> str:
        """Location prefix extracted from serverUrl (e.g. usw3, use4, usw1)."""
        if not self._pod_location:
            self.login()
        return self._pod_location

    @property
    def server_url(self) -> str:
        if not self._server_url:
            self.login()
        return self._server_url

    @property
    def url_prefix(self) -> str:
        """MCP URL prefix for this pod, looked up from MCP_URL_PREFIX_MAP.

        Falls back to MCP_URL_PREFIX_DEFAULT (default: a2e-prod).
        """
        import json
        raw = os.environ.get("MCP_URL_PREFIX_MAP", "{}").strip()
        try:
            prefix_map = json.loads(raw)
        except json.JSONDecodeError:
            prefix_map = {}
        default = os.environ.get("MCP_URL_PREFIX_DEFAULT", "a2e-prod").strip()
        return prefix_map.get(self.pod, default)


# ---------------------------------------------------------------------------
# Session cache — keyed by sha256(pod:username:password)
# ---------------------------------------------------------------------------

_session_cache: dict = {}
_cache_lock = threading.Lock()


def _cache_key(pod: str, username: str, password: str) -> str:
    raw = f"{pod}:{username}:{password}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_cached_session(pod: str, username: str, password: str) -> Optional[InformaticaSession]:
    key = _cache_key(pod, username, password)
    timeout = _get_timeout_minutes()
    with _cache_lock:
        entry = _session_cache.get(key)
        if entry is None:
            return None
        if datetime.utcnow() - entry["authed_at"] > timedelta(minutes=timeout):
            del _session_cache[key]
            return None
        return entry["session"]


def _store_session(pod: str, username: str, password: str, session: InformaticaSession) -> None:
    key = _cache_key(pod, username, password)
    with _cache_lock:
        _session_cache[key] = {"session": session, "authed_at": datetime.utcnow()}


# ---------------------------------------------------------------------------
# Local dev session (credentials from .env)
# ---------------------------------------------------------------------------
_local_session: Optional[InformaticaSession] = None


def get_session() -> InformaticaSession:
    """Return an authenticated session for the current request.

    Container mode: credentials from request_credentials context var (X-IDMC-Token).
    Local mode: credentials from .env on disk.

    Sessions are cached per credential set for SESSION_TIMEOUT_MINUTES.
    """
    creds = request_credentials.get()
    if creds:
        pod      = creds["pod"]
        username = creds["username"]
        password = creds["password"]

        session = _get_cached_session(pod, username, password)
        if session is None:
            session = InformaticaSession(pod=pod, username=username, password=password)
            session.login()
            _store_session(pod, username, password, session)
        return session

    # Local mode: lazy singleton
    global _local_session
    if _local_session is None:
        path = str(Path(__file__).parent / ".env")
        load_dotenv(path, override=True)
        pod      = os.environ.get("pod", "").strip()
        username = os.environ.get("username", "").strip()
        password = os.environ.get("password", "").strip()
        if not pod or not username or not password:
            raise AuthError(".env must contain: pod, username, password")
        _local_session = InformaticaSession(pod=pod, username=username, password=password)
    return _local_session
