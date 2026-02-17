"""Custom RQ Worker with unified logging.

Launch with:
    rq worker --worker-class worker_class.PipelitWorker workflows --with-scheduler
"""

from __future__ import annotations

import os

from rq import SimpleWorker

from logging_config import setup_logging


class PipelitWorker(SimpleWorker):
    def __init__(self, *args, **kwargs):
        setup_logging(f"Worker-{os.getpid()}")
        super().__init__(*args, **kwargs)

    def work(self, *args, **kwargs):
        kwargs.setdefault("with_scheduler", True)
        return super().work(*args, **kwargs)
