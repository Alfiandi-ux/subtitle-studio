"""Antrean job latar belakang dengan progres dan pembatalan."""
from __future__ import annotations

import queue
import shutil
import threading
import uuid
from datetime import datetime, timezone

from . import config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Job:
    def __init__(self, kind: str, label: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.label = label
        self.status = "queued"  # queued | running | done | error | cancelled
        self.progress = None
        self.stage = "Menunggu antrean"
        self.message = ""
        self.result = None
        self.error = None
        self.created_at = _now()
        self.updated_at = self.created_at
        self.cancel_event = threading.Event()
        self.dir = config.TMP_DIR / self.id
        self.dir.mkdir(parents=True, exist_ok=True)

    def update(self, *, progress=None, stage=None, message=None) -> None:
        if progress is not None:
            self.progress = max(0, min(100, float(progress)))
        if stage is not None:
            self.stage = stage
        if message is not None:
            self.message = message
        self.updated_at = _now()

    def set_progress(self, value: float, stage: str | None = None) -> None:
        self.update(progress=value, stage=stage)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "progress": None if self.progress is None else round(self.progress, 1),
            "stage": self.stage,
            "message": self.message,
            "error": self.error,
            "result": self.result,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class JobManager:
    def __init__(self, workers: int = 1):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._queue: queue.Queue[Job] = queue.Queue()
        for index in range(max(1, workers)):
            thread = threading.Thread(
                target=self._worker, name=f"job-worker-{index}", daemon=True
            )
            thread.start()

    def submit(self, kind: str, label: str, fn) -> Job:
        job = Job(kind, label)
        with self._lock:
            self._jobs[job.id] = job
        self._queue.put((job, fn))
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, limit: int = 20) -> list[dict]:
        with self._lock:
            jobs = sorted(
                self._jobs.values(), key=lambda j: j.created_at, reverse=True
            )[:limit]
        return [job.to_dict() for job in jobs]

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job.status in ("done", "error", "cancelled"):
            return False
        job.cancel_event.set()
        if job.status == "queued":
            job.status = "cancelled"
            job.stage = "Dibatalkan"
            job.updated_at = _now()
        else:
            job.stage = "Membatalkan…"
        return True

    def _worker(self) -> None:
        while True:
            job, fn = self._queue.get()
            if job.cancel_event.is_set() or job.status == "cancelled":
                job.status = "cancelled"
                job.stage = "Dibatalkan"
                job.updated_at = _now()
                self._cleanup(job)
                self._queue.task_done()
                continue

            job.status = "running"
            job.stage = "Memulai…"
            job.progress = 0
            job.updated_at = _now()
            try:
                result = fn(job)
                if job.cancel_event.is_set():
                    job.status = "cancelled"
                    job.stage = "Dibatalkan"
                else:
                    job.status = "done"
                    job.progress = 100
                    job.stage = "Selesai"
                    job.result = result
            except Exception as exc:  # noqa: BLE001 - pesan diteruskan ke UI
                if job.cancel_event.is_set():
                    job.status = "cancelled"
                    job.stage = "Dibatalkan"
                else:
                    job.status = "error"
                    job.error = str(exc) or exc.__class__.__name__
                    job.stage = "Gagal"
            finally:
                job.updated_at = _now()
                self._cleanup(job)
                self._queue.task_done()

    @staticmethod
    def _cleanup(job: Job) -> None:
        shutil.rmtree(job.dir, ignore_errors=True)
