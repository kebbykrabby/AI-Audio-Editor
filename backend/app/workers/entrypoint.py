"""Worker entrypoint — import side-effects register the broker and actors.

Launch with:

    dramatiq app.workers.entrypoint --processes 2 --threads 4

For development, a single process + single thread is fine:

    dramatiq app.workers.entrypoint -p 1 -t 1
"""

from app.workers.ai_worker import run_ai_detect_fillers_actor  # noqa: F401
from app.workers.broker import broker  # noqa: F401
from app.workers.export_worker import run_export_actor  # noqa: F401
from app.workers.operation_worker import run_operation_actor  # noqa: F401
from app.workers.upload_worker import run_upload_actor  # noqa: F401
