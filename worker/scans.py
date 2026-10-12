import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
from threading import Event
from uuid import UUID, uuid4
from starlette.concurrency import run_in_threadpool
from worker.events import InvalidAcknowledgement

def scan_once(owner, window_days, max_pages, stop):
    trace = str(uuid4()); seen = set()
    for page in range(1, max_pages + 1):
        if stop.is_set(): return None
        result = owner.request("GET", f"/api/v1/stock?page={page}&limit=100", None, trace)
        try:
            if set(result) != {"data", "meta"}: raise ValueError("Invalid stock envelope")
            rows, meta = result["data"], result["meta"]
            if not isinstance(rows, list) or not isinstance(meta, dict) or set(meta) != {"page", "limit", "total"}:
                raise ValueError("Invalid page shape")
            if any(type(meta[key]) is not int for key in meta) or meta["page"] != page or meta["limit"] != 100 or meta["total"] < 0:
                raise ValueError("Invalid page metadata")
            if len(rows) != min(100, max(0, meta["total"] - (page-1)*100)):
                raise ValueError("Incomplete stock page")
            ids = [row["lotId"] for row in rows]
            if any(not isinstance(lot, str) or str(UUID(lot)) != lot for lot in ids):
                raise ValueError("Canonical lot required")
        except (ValueError, TypeError, KeyError) as error:
            raise InvalidAcknowledgement("Invalid stock page") from error
        for lot in ids:
            if stop.is_set(): return None
            if lot not in seen:
                owner.evaluate_lot(lot, window_days, trace); seen.add(lot)
        if page*100 >= meta["total"]: return len(seen)
    raise RuntimeError("Expiry scan page limit reached")

@asynccontextmanager
async def scan_lifespan(app, owner, enabled, window_days, interval, max_pages):
    stop = Event(); wake = asyncio.Event()
    app.state.expiry_scan = {"status": "DISABLED", "attempts": 0, "evaluated": None, "lastCompletedAt": None}
    async def run():
        while not stop.is_set():
            state = dict(app.state.expiry_scan, status="RUNNING", attempts=app.state.expiry_scan["attempts"]+1, evaluated=None)
            app.state.expiry_scan = state
            try:
                count = await run_in_threadpool(scan_once, owner, window_days, max_pages, stop)
                if count is not None:
                    app.state.expiry_scan = dict(state, status="COMPLETE", evaluated=count,
                        lastCompletedAt=datetime.now(timezone.utc).isoformat())
            except (RuntimeError, ValueError) as error:
                logging.getLogger(__name__).warning("Expiry scan failed (%s)", type(error).__name__)
                app.state.expiry_scan = dict(state, status="FAILED")
            try: await asyncio.wait_for(wake.wait(), timeout=interval)
            except TimeoutError: pass
    task = asyncio.create_task(run()) if enabled else None
    try: yield
    finally:
        stop.set(); wake.set()
        if task is not None: await task
