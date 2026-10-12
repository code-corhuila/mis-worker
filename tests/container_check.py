import json
import sys
from pathlib import Path
import httpx

fixture = Path('/fixture')
event = json.loads((fixture/'event.json').read_text())
with httpx.Client(timeout=5, trust_env=False) as client:
    def send(token, body=event):
        return client.post('http://worker:8080/internal/events/stock-changed', json=body,
            headers={'Authorization': 'Bearer '+(fixture/token).read_text()})
    def event_rows():
        return [row for row in client.get('http://inventory:8080/observations').json() if row['trace'] == event['traceId']]
    if len(sys.argv) > 1 and sys.argv[1] == 'renewed':
        response = send('relay.jwt')
        assert response.status_code == 200 and response.json()['accepted'] is True
        rows = event_rows()
        assert len(rows) == 6 and rows[0]['jti'] != rows[-1]['jti']
        assert rows[-1]['lotId'] == event['lotId']
        print('Renewed Worker token observed over container HTTP.')
    else:
        assert client.get('http://worker:8080/health').status_code == 200
        import time
        for _ in range(50):
            state = client.get('http://worker:8080/health').json()['expiryScan']
            if state['status'] == 'COMPLETE': break
            time.sleep(.1)
        assert state['status'] == 'COMPLETE' and state['evaluated'] == 1
        scans = client.get('http://inventory:8080/observations').json()
        assert any(row.get('lotId') == event['lotId'] and row['trace'] != event['traceId'] for row in scans)
        assert client.post('http://worker:8080/internal/events/stock-changed', json=event).status_code == 401
        assert send('expired.jwt').status_code == 401
        assert send('wrong.jwt').status_code == 403
        assert send('relay.jwt', dict(event, delta=9)).status_code == 400
        for _ in range(2):
            response = send('relay.jwt')
            assert response.status_code == 200
            assert response.json() == {'eventId': event['eventId'], 'sequence': event['sequence'], 'accepted': True}
        rows = event_rows()
        assert len(rows) == 4 and all(row['trace'] == event['traceId'] for row in rows)
        assert all(row['lotId'] == event['lotId'] for row in rows[1::2])
        print('Signed event receipt followed by expiry evaluation verified, including replay; owner is a stub.')
