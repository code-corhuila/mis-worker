import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4
import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from worker.transport import Settings, create_app
from test_events import EVENT, ID

class TransportTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="mis-worker-transport-")
        self.addCleanup(self.folder.cleanup)
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public = Path(self.folder.name) / "public.pem"
        self.token_file = Path(self.folder.name) / "service.jwt"
        self.public.write_bytes(self.key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
        self.relay = str(uuid4()); self.worker = str(uuid4())
        self.settings = Settings(self.public, self.token_file, "dev-key", "dev", self.relay, self.worker, "http://inventory:8080")
        self.calls = []
        self.response = {"eventId": ID, "sequence": 1, "applied": True}
        self.status = 200; self.error = None; self.raw_response = None
        self.token_file.write_text(self.token("mis-worker"), encoding="ascii")
        self.app = create_app(self.settings, httpx.MockTransport(self.owner))

    def request(self, **kwargs):
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://worker") as client:
                return await client.post("/internal/events/stock-changed", **kwargs)
        return asyncio.run(send())

    def token(self, service="mis-inventory-relay", **patch):
        now = int(time.time())
        claims = dict(sub=self.worker if service == "mis-worker" else self.relay, iss="mis-security",
            aud="mis-api" if service == "mis-worker" else "mis-events", roles=["INVENTORY"] if service == "mis-worker" else [],
            service=service, environment="dev", iat=now, exp=now+3600, jti=str(uuid4()))
        claims.update(patch)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "dev-key"})

    def owner(self, request):
        self.calls.append(request)
        if self.error:
            raise self.error
        if self.raw_response is not None:
            return httpx.Response(self.status, content=self.raw_response)
        return httpx.Response(self.status, json=self.response)

    def post(self, token=None, raw=None, **kwargs):
        headers = {"Authorization": "Bearer " + (token if token is not None else self.token()), "Content-Type": "application/json"}
        return self.request(headers=headers,
            content=json.dumps(EVENT).encode() if raw is None else raw, **kwargs)

    def test_signed_relay_and_owner_confirmed_ack(self):
        for applied in (True, False):
            self.response["applied"] = applied
            result = self.post()
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json(), {"eventId": ID, "sequence": 1, "accepted": True})
        request = self.calls[-1]
        self.assertEqual(str(request.url), "http://inventory:8080/api/v1/internal/events/stock-changed")
        self.assertEqual(json.loads(request.content), EVENT)
        self.assertEqual(request.headers["X-Correlation-Id"], EVENT["traceId"])
        outgoing = jwt.decode(request.headers["Authorization"][7:], self.key.public_key(), algorithms=["RS256"], audience="mis-api")
        self.assertEqual(outgoing["sub"], self.worker)

    def test_missing_invalid_expired_foreign_and_wrong_audience_tokens(self):
        now = int(time.time())
        foreign = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        valid = self.token()
        payload = jwt.decode(valid, options={"verify_signature": False})
        tokens = ["invalid", self.token(exp=now-1, iat=now-3601), self.token(aud="mis-api"),
            self.token(environment="qa"), self.token(iss="foreign"), self.token(exp=now+7200),
            jwt.encode(payload, foreign, algorithm="RS256", headers={"kid": "dev-key"}),
            jwt.encode(payload, self.key, algorithm="RS256", headers={"kid": "qa-key"})]
        self.assertEqual(self.request(json=EVENT).status_code, 401)
        for token in tokens:
            with self.subTest(token=token[:10]): self.assertEqual(self.post(token=token).status_code, 401)
        self.assertEqual(self.calls, [])

    def test_signed_wrong_service_subject_or_roles_cannot_call_owner(self):
        for token in (self.token(service="human"), self.token(sub=str(uuid4())), self.token(roles=["INVENTORY"]),
                      self.token("mis-worker", aud="mis-events")):
            self.assertEqual(self.post(token=token).status_code, 403)
        self.assertEqual(self.calls, [])

    def test_body_validation_and_size_before_owner_call(self):
        for raw in (b"{", b"\xff", b'{"eventId":"a","eventId":"b"}', json.dumps(dict(EVENT, delta=9)).encode()):
            self.assertEqual(self.post(raw=raw).status_code, 400)
        self.assertEqual(self.post(raw=b"x"*65537).status_code, 413)
        async def chunks():
            yield b"x"*40000
            yield b"x"*40000
        self.assertEqual(self.post(raw=chunks()).status_code, 413)
        self.assertEqual(self.request(content="{}",
            headers={"Authorization": "Bearer " + self.token()}).status_code, 415)
        self.assertEqual(self.calls, [])

    def test_owner_error_timeout_and_wrong_ack_never_accept(self):
        for status in (401, 409, 503, 302):
            self.status = status
            self.assertEqual(self.post().status_code, 503)
        self.status = 200
        self.error = httpx.ReadTimeout("synthetic timeout")
        self.assertEqual(self.post().status_code, 503)
        self.error = None
        receipt = dict(self.response)
        for response in ({}, dict(receipt, sequence=2), dict(receipt, applied="yes"),
                         dict(receipt, eventId=str(uuid4())), dict(receipt, extra="no")):
            self.response = response
            self.assertEqual(self.post().status_code, 502)

    def test_malformed_duplicate_and_oversized_owner_response_never_accept(self):
        for raw in (b"{", b'{"eventId":"a","eventId":"b"}', b"x"*65537,
                    b'{"sequence":'+b'1'*5000+b'}'):
            self.raw_response = raw
            self.assertEqual(self.post().status_code, 502)

    def test_outgoing_identity_rejected_and_token_reread_after_renewal(self):
        now = int(time.time())
        for token in (self.token(), self.token("mis-worker", sub=str(uuid4())),
                      self.token("mis-worker", roles=["ADMIN"]), self.token("mis-worker", iat=now-3601, exp=now-1)):
            self.token_file.write_text(token, encoding="ascii")
            self.assertEqual(self.post().status_code, 503)
        self.assertEqual(self.calls, [])
        first = self.token("mis-worker")
        self.token_file.write_text(first, encoding="ascii")
        self.assertEqual(self.post().status_code, 200)
        renewed = self.token("mis-worker")
        self.token_file.write_text(renewed, encoding="ascii")
        self.assertEqual(self.post().status_code, 200)
        self.assertNotEqual(first, renewed)
        self.assertEqual(self.calls[-1].headers["Authorization"], "Bearer " + renewed)
        self.token_file.unlink()
        self.assertEqual(self.post().status_code, 503)

    def test_fail_closed_configuration(self):
        from dataclasses import replace
        for patch in (dict(worker_subject=self.relay), dict(relay_subject="bad"), dict(environment="other"),
                      dict(owner_url="http://user:password@inventory"), dict(owner_url="http://inventory/path"), dict(key_id="")):
            with self.assertRaises(ValueError): create_app(replace(self.settings, **patch))
        self.public.write_text("not-a-public-key", encoding="ascii")
        with self.assertRaises(ValueError): create_app(self.settings)

if __name__ == "__main__":
    unittest.main()
