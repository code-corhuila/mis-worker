import asyncio
from dataclasses import replace
from threading import Event
import unittest
from uuid import uuid4
from fastapi import FastAPI
import httpx
import jwt
from worker.events import InvalidAcknowledgement
from worker.scans import scan_once, scan_lifespan
from worker.transport import create_app

class Owner:
    def __init__(self, total=201):
        self.ids = [str(uuid4()) for _ in range(total)]
        self.calls = []; self.evaluated = []; self.failure = None
    def request(self, method, path, body, trace):
        self.calls.append((method,path,body,trace))
        if self.failure: raise self.failure
        page = int(path.split("page=")[1].split("&")[0])
        return {"data": [{"lotId": lot} for lot in self.ids[(page-1)*100:page*100]], "meta": {"page": page, "limit": 100, "total": len(self.ids)}}
    def evaluate_lot(self, lot, window, trace): self.evaluated.append((lot,window,trace))

class ScanTest(unittest.TestCase):
    def test_all_pages_and_only_owned_ids_are_evaluated(self):
        owner = Owner(); owner.ids[100] = owner.ids[0]
        self.assertEqual(scan_once(owner,30,100,Event()),200)
        self.assertEqual(len(owner.calls),3)
        self.assertEqual({lot for lot,_,_ in owner.evaluated},set(owner.ids))
        self.assertTrue(all(window == 30 and trace == owner.calls[0][3] for _,window,trace in owner.evaluated))
        self.assertTrue(all(method == "GET" and body is None for method,_,body,_ in owner.calls))

    def test_empty_and_exactly_full_final_page_terminate(self):
        for total in (0,100):
            owner = Owner(total)
            self.assertEqual(scan_once(owner,30,1,Event()),total)
            self.assertEqual(len(owner.calls),1)

    def test_rejects_invalid_or_incomplete_stock_pages(self):
        for result in ({}, {"data":[],"meta":{"page":1,"limit":100,"total":1}},
            {"data":[],"meta":{"page":True,"limit":100,"total":0}},
            {"data":[{"lotId":"bad"}],"meta":{"page":1,"limit":100,"total":1}},
            {"data":[{}],"meta":{"page":1,"limit":100,"total":1}}):
            owner = Owner(); owner.request = lambda *args: result
            with self.assertRaises(InvalidAcknowledgement): scan_once(owner,30,10,Event())
            self.assertEqual(owner.evaluated,[])

    def test_limits_and_failed_evaluation_never_report_complete(self):
        with self.assertRaises(RuntimeError): scan_once(Owner(),30,1,Event())
        owner = Owner(1)
        def fail(*args): raise RuntimeError("Synthetic failure")
        owner.evaluate_lot = fail
        with self.assertRaises(RuntimeError): scan_once(owner,30,100,Event())

    def test_stop_prevents_new_calls_between_lots(self):
        owner = Owner(); stop = Event()
        def evaluate(*args): stop.set()
        owner.evaluate_lot = evaluate
        self.assertIsNone(scan_once(owner,30,100,stop))
        self.assertEqual(len(owner.calls),1)

    def test_lifespan_runs_immediately_retries_and_stops(self):
        async def run():
            app = FastAPI(); owner = Owner(1); calls = 0
            original = owner.request
            def request(*args):
                nonlocal calls
                calls += 1
                if calls == 1: raise RuntimeError("Synthetic failure")
                return original(*args)
            owner.request = request
            async with scan_lifespan(app,owner,True,30,.01,100):
                for _ in range(200):
                    if app.state.expiry_scan["status"] == "COMPLETE": break
                    await asyncio.sleep(.005)
                self.assertEqual(app.state.expiry_scan["evaluated"],1)
                self.assertGreaterEqual(app.state.expiry_scan["attempts"],2)
                self.assertIsNotNone(app.state.expiry_scan["lastCompletedAt"])
            stopped = calls; await asyncio.sleep(.03); self.assertEqual(calls,stopped)
            async with scan_lifespan(app,owner,False,30,.01,100):
                self.assertEqual(app.state.expiry_scan["status"],"DISABLED")
                self.assertEqual(calls,stopped)
        asyncio.run(run())

    def test_signed_http_scan_without_stock_event(self):
        from test_transport import TransportTest
        fixture = TransportTest(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        def owner(request):
            fixture.calls.append(request)
            if request.method == "GET":
                return httpx.Response(200,json={"data":[{"lotId":fixture.worker}],"meta":{"page":1,"limit":100,"total":1}})
            return httpx.Response(200,json={"lotId":fixture.worker,"alertPresent":False,"alert":None})
        app = create_app(replace(fixture.settings,expiry_enabled=True,expiry_scan_enabled=True),httpx.MockTransport(owner))
        async def run():
            async with app.router.lifespan_context(app):
                for _ in range(200):
                    if app.state.expiry_scan["status"] == "COMPLETE": break
                    await asyncio.sleep(.005)
                self.assertEqual(app.state.expiry_scan["evaluated"],1)
        asyncio.run(run())
        self.assertEqual([call.url.path for call in fixture.calls],["/api/v1/stock","/api/v1/internal/alerts/expiry/evaluate"])
        for call in fixture.calls:
            identity = jwt.decode(call.headers["Authorization"][7:],fixture.key.public_key(),algorithms=["RS256"],audience="mis-api")
            self.assertEqual(identity["sub"],fixture.worker)

    def test_scan_settings_fail_closed(self):
        from test_transport import TransportTest
        fixture = TransportTest(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        for patch in (dict(expiry_scan_enabled=True),dict(expiry_scan_enabled="true"),dict(expiry_interval_seconds=59),
                      dict(expiry_interval_seconds=True),dict(expiry_max_pages=0),dict(expiry_max_pages=1001)):
            with self.assertRaises(ValueError): create_app(replace(fixture.settings,**patch))
