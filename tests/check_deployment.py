import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from uuid import uuid4
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from test_events import EVENT
project = 'mis-worker-check-'+uuid4().hex[:12]
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
worker, relay = str(uuid4()), str(uuid4())
def token(service, **patch):
    now = int(time.time())
    claims = dict(sub=worker if service == 'mis-worker' else relay, service=service, environment='dev',
        iss='mis-security', aud='mis-api' if service == 'mis-worker' else 'mis-events',
        roles=['INVENTORY'] if service == 'mis-worker' else [], iat=now, exp=now+3600, jti=str(uuid4()))
    claims.update(patch)
    return jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'synthetic-dev'})

with tempfile.TemporaryDirectory(prefix=project+'-') as temporary:
    fixture = Path(temporary)
    # Only synthetic public keys/tokens leave memory; runtime user must read the fixture on Linux CI.
    fixture.chmod(0o755)
    credentials = fixture/'worker'; credentials.mkdir(mode=0o755)
    (credentials/'public.pem').write_bytes(key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    (credentials/'service.jwt').write_text(token('mis-worker'), encoding='ascii')
    (fixture/'relay.jwt').write_text(token('mis-inventory-relay'), encoding='ascii')
    (fixture/'expired.jwt').write_text(token('mis-inventory-relay', iat=int(time.time())-3601, exp=int(time.time())-1), encoding='ascii')
    (fixture/'wrong.jwt').write_text(token('human'), encoding='ascii')
    (fixture/'identity.json').write_text(json.dumps({'worker': worker}), encoding='ascii')
    (fixture/'event.json').write_text(json.dumps(EVENT), encoding='ascii')
    for file in fixture.rglob('*'):
        if file.is_file(): file.chmod(0o644)
    env = dict(os.environ, WORKER_IMAGE=project, WORKER_TEST_FIXTURE=str(fixture), WORKER_CREDENTIALS_PATH=str(credentials),
        WORKER_KEY_ID='synthetic-dev', WORKER_ENVIRONMENT='dev', WORKER_SERVICE_SUBJECT=worker, RELAY_SERVICE_SUBJECT=relay)
    compose = ['docker', 'compose', '-p', project, '-f', str(root/'tests/compose.deployment.yml')]
    def run(arguments, capture=False):
        return subprocess.run(compose+arguments, env=env, check=True, text=True, capture_output=capture)
    try:
        model = json.loads(run(['config', '--format', 'json'], True).stdout)
        service = model['services']['worker']
        assert not service.get('ports') and service['read_only'] and 'ALL' in service['cap_drop']
        assert all(mount.get('read_only') for mount in service['volumes'])
        for missing in ('WORKER_KEY_ID', 'WORKER_CREDENTIALS_PATH', 'WORKER_ENVIRONMENT', 'WORKER_SERVICE_SUBJECT', 'RELAY_SERVICE_SUBJECT'):
            incomplete = dict(env); incomplete.pop(missing)
            failure = subprocess.run(compose+['config', '--quiet'], env=incomplete, capture_output=True)
            assert failure.returncode != 0, missing+' must fail closed'
        run(['build', 'worker'])
        run(['up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '120', 'inventory', 'worker'])
        run(['run', '--rm', '--no-deps', 'deployment-check'])
        temp_token = credentials/'renewed.tmp'
        temp_token.write_text(token('mis-worker'), encoding='ascii'); temp_token.chmod(0o644)
        temp_token.replace(credentials/'service.jwt')
        run(['run', '--rm', '--no-deps', 'deployment-check', 'renewed'])
        container = run(['ps', '-q', 'worker'], True).stdout.strip()
        details = json.loads(subprocess.run(['docker', 'inspect', container], check=True, capture_output=True, text=True).stdout)[0]
        assert details['Config']['User'] == '10001:10001' and details['HostConfig']['ReadonlyRootfs']
        assert not details['HostConfig']['PortBindings'] and 'ALL' in details['HostConfig']['CapDrop']
        assert 'no-new-privileges:true' in details['HostConfig']['SecurityOpt']
        print('Worker deployment passed: synthetic credentials; no live Inventory persistence tested.')
    finally:
        run(['down', '--volumes', '--remove-orphans'])
