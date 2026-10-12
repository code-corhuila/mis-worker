import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import jwt

fixture = Path('/fixture')
identity = json.loads((fixture/'identity.json').read_text())
observations = []
seen = set()

class Owner(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def respond(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        self.respond(200, observations if self.path == '/observations' else {'status': 'UP'})
    def do_POST(self):
        try:
            assert self.path in ('/api/v1/internal/events/stock-changed', '/api/v1/internal/alerts/expiry/evaluate')
            claims = jwt.decode(self.headers['Authorization'][7:], (fixture/'worker/public.pem').read_text(),
                algorithms=['RS256'], audience='mis-api', issuer='mis-security')
            assert claims['sub'] == identity['worker'] and claims['service'] == 'mis-worker' and claims['roles'] == ['INVENTORY']
            event = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path.endswith('/alerts/expiry/evaluate'):
                assert set(event) == {'lotId', 'windowDays'} and event['windowDays'] == 30
                observations.append({'lotId': event['lotId'], 'trace': self.headers['X-Correlation-Id'], 'jti': claims['jti']})
                self.respond(200, {'lotId': event['lotId'], 'alertPresent': False, 'alert': None})
                return
            observations.append({'eventId': event['eventId'], 'trace': self.headers['X-Correlation-Id'], 'jti': claims['jti']})
            applied = event['eventId'] not in seen
            seen.add(event['eventId'])
            self.respond(200, {'eventId': event['eventId'], 'sequence': event['sequence'], 'applied': applied})
        except (AssertionError, ValueError, KeyError, jwt.PyJWTError): self.respond(403, {'error': 'REJECTED'})

HTTPServer(('0.0.0.0', 8080), Owner).serve_forever()
