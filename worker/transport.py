from dataclasses import dataclass
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4
import httpx
import jwt
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from worker.events import consume, InvalidEvent, InvalidAcknowledgement, unique_object

class AuthenticationError(ValueError):
    pass

class OwnerUnavailable(RuntimeError):
    pass

@dataclass(frozen=True)
class Settings:
    public_key: Path
    token_file: Path
    key_id: str
    environment: str
    relay_subject: str
    worker_subject: str
    owner_url: str

def canonical(value):
    return isinstance(value, str) and str(UUID(value)) == value and UUID(value).int != 0

def create_app(settings: Settings, transport=None):
    for subject in (settings.relay_subject, settings.worker_subject):
        if not canonical(subject):
            raise ValueError("Canonical service subjects required")
    if settings.relay_subject == settings.worker_subject or settings.environment not in ("dev", "qa", "main") or not settings.key_id:
        raise ValueError("Distinct configured identities required")
    url = urlsplit(settings.owner_url)
    if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ("", "/"):
        raise ValueError("Fixed owner origin required")
    key = load_pem_public_key(settings.public_key.read_bytes())
    if not isinstance(key, RSAPublicKey) or key.key_size < 2048:
        raise ValueError("RSA public key required")

    def authenticate(token, audience):
        try:
            if not isinstance(token, str) or len(token) > 8192:
                raise ValueError("Invalid token size")
            if jwt.get_unverified_header(token).get("kid") != settings.key_id:
                raise ValueError("Unknown key")
            claims = jwt.decode(token, key, algorithms=["RS256"], issuer="mis-security", audience=audience,
                options={"require": ["sub", "iss", "aud", "iat", "exp", "jti", "service", "environment", "roles"], "strict_aud": True})
            if not canonical(claims["sub"]) or not canonical(claims["jti"]) or claims["environment"] != settings.environment:
                raise ValueError("Invalid identity")
            if type(claims["exp"]) is not int or type(claims["iat"]) is not int or not 60 <= claims["exp"] - claims["iat"] <= 3600:
                raise ValueError("Invalid token lifetime")
            return claims
        except (jwt.PyJWTError, ValueError, TypeError, KeyError) as error:
            raise AuthenticationError("Invalid service credential") from error

    class HttpOwner:
        def apply(self, event):
            try:
                token = settings.token_file.read_text(encoding="ascii").strip()
                identity = authenticate(token, "mis-api")
                if identity["service"] != "mis-worker" or identity["sub"] != settings.worker_subject or identity["roles"] != ["INVENTORY"]:
                    raise AuthenticationError("Wrong outgoing identity")
                with httpx.Client(timeout=5.0, follow_redirects=False, trust_env=False, transport=transport) as client:
                    with client.stream("POST", settings.owner_url.rstrip("/") + "/api/v1/internal/events/stock-changed",
                        headers={"Authorization": "Bearer " + token, "X-Correlation-Id": event.payload["traceId"]}, json=dict(event.payload)) as response:
                        if response.status_code != 200:
                            raise OwnerUnavailable("Owner did not confirm")
                        body = bytearray()
                        for chunk in response.iter_bytes(chunk_size=4096):
                            body.extend(chunk)
                            if len(body) > 65536:
                                raise InvalidAcknowledgement("Owner response too large")
                        result = json.loads(body, object_pairs_hook=unique_object)
                        if not isinstance(result, dict) or set(result) != {"eventId", "sequence", "applied"}:
                            raise InvalidAcknowledgement("Invalid owner response")
                        return result
            except (OSError, UnicodeError, AuthenticationError, httpx.HTTPError) as error:
                raise OwnerUnavailable("Owner unavailable") from error
            except ValueError as error:
                raise InvalidAcknowledgement("Invalid owner response") from error

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def failure(status, code, trace):
        return JSONResponse({"error": code, "message": code, "traceId": trace}, status_code=status)

    @app.get("/health")
    def health():
        return {"status": "UP"}

    @app.post("/internal/events/stock-changed")
    async def receive(request: Request):
        trace = str(uuid4())
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            return failure(401, "UNAUTHENTICATED", trace)
        try:
            identity = authenticate(authorization[7:], "mis-events")
        except AuthenticationError:
            return failure(401, "UNAUTHENTICATED", trace)
        if identity["service"] != "mis-inventory-relay" or identity["sub"] != settings.relay_subject or identity["roles"] != []:
            return failure(403, "FORBIDDEN", trace)
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            return failure(415, "UNSUPPORTED_MEDIA_TYPE", trace)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                return failure(413, "EVENT_TOO_LARGE", trace)
        try:
            return await run_in_threadpool(consume, bytes(body), HttpOwner())
        except InvalidEvent:
            return failure(400, "INVALID_EVENT", trace)
        except InvalidAcknowledgement:
            return failure(502, "INVALID_OWNER_ACK", trace)
        except OwnerUnavailable:
            return failure(503, "OWNER_UNAVAILABLE", trace)

    return app

def from_environment():
    return create_app(Settings(Path(os.environ["WORKER_PUBLIC_KEY"]), Path(os.environ["WORKER_TOKEN_FILE"]),
        os.environ["WORKER_KEY_ID"], os.environ["WORKER_ENVIRONMENT"], os.environ["RELAY_SERVICE_SUBJECT"],
        os.environ["WORKER_SERVICE_SUBJECT"], os.environ["INVENTORY_ORIGIN"]))
