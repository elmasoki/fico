"""Background jobs for long running work (data dictionary load, relation checks,
value search, profiling, data extraction) with progress and cancellation.

Jobs run in daemon threads (at most `max_parallel` at a time) and report into
the `jobs` table, so the UI can show progress and the result afterwards."""
from __future__ import annotations

import logging
import threading
import traceback
from typing import Callable, Dict, Optional

from .store import Store, now

log = logging.getLogger(__name__)

JOB_KINDS = {
    "catalog": "Veri sözlüğü",
    "relcheck": "İlişki doğrulama",
    "tablesearch": "Değer arama",
    "profile": "Veri profili",
    "extract": "Veri çıkarma",
}


class JobCancelled(Exception):
    pass


class JobContext:
    def __init__(self, runner: "JobRunner", job_id: int):
        self.runner = runner
        self.job_id = job_id
        self.message = ""

    def progress(self, percent: float, message: Optional[str] = None):
        self.check()
        if message is not None:
            self.message = message
        self.runner.store.update_job(self.job_id, progress=max(0, min(100, int(percent))),
                                     message=self.message)

    def check(self):
        if self.runner.cancelled(self.job_id):
            raise JobCancelled()


class JobRunner:
    def __init__(self, store: Store, sync: bool = False, max_parallel: int = 2):
        self.store = store
        self.sync = sync
        self._cancel: Dict[int, bool] = {}
        self._slots = threading.Semaphore(max_parallel)
        store.fail_stale_jobs()

    def submit(self, kind: str, title: str, fn: Callable[[JobContext], object],
               params: Optional[dict] = None) -> int:
        job_id = self.store.create_job(kind, title, params)
        if self.sync:
            self._run(job_id, fn)
        else:
            threading.Thread(target=self._run, args=(job_id, fn), daemon=True,
                             name="job-%d" % job_id).start()
        return job_id

    def cancel(self, job_id: int):
        self._cancel[job_id] = True

    def cancelled(self, job_id: int) -> bool:
        return self._cancel.get(job_id, False)

    def _run(self, job_id: int, fn):
        ctx = JobContext(self, job_id)
        with self._slots:
            self.store.update_job(job_id, status="running", started_at=now())
            try:
                result = fn(ctx)
                self.store.update_job(job_id, status="done", progress=100, result=result,
                                      message=ctx.message or "Tamamlandı", finished_at=now())
            except JobCancelled:
                self.store.update_job(job_id, status="cancelled", message="İptal edildi", finished_at=now())
            except Exception as exc:  # report, never crash the thread silently
                log.error("job %s failed\n%s", job_id, traceback.format_exc())
                self.store.update_job(job_id, status="failed", message=str(exc)[:2000], finished_at=now())
            finally:
                self._cancel.pop(job_id, None)
