"""Try the engine API on a COPY of your real data, in mock mode. Your real files are never touched.

    python scripts\\api_sandbox.py            (listens on 127.0.0.1:8001, Ctrl+C to stop)

It copies ``data/jobpilot.db`` and ``data/answers.json`` into a fresh temporary folder and starts the API on
those copies, always in ``mock`` mode (fake search vectors), whatever ``settings.json`` says. Answer a question,
approve a wording, delete an answer: all of it happens in the copy, which is deleted when you stop.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402

from engine import api  # noqa: E402
from engine.db import DB_PATH  # noqa: E402
from engine.profile import ANSWERS_PATH  # noqa: E402
from engine.settings import Settings  # noqa: E402

PORT = 8001


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="jobpilot-sandbox-") as folder:
        sandbox = Path(folder)
        db_copy, answers_copy = sandbox / DB_PATH.name, sandbox / ANSWERS_PATH.name
        shutil.copy2(DB_PATH, db_copy)
        shutil.copy2(ANSWERS_PATH, answers_copy)
        print(f"Sandbox folder (deleted when you stop): {sandbox}")
        print(f"API: http://127.0.0.1:{PORT}   mode: mock   Ctrl+C to stop")
        app = api.create_app(Settings(run_mode="mock"), db_path=db_copy, answers_path=answers_copy)
        uvicorn.run(app, host=api.check_local_host("127.0.0.1"), port=PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
