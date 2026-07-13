"""webui/tests conftest: ensure webinfer modules are importable.

The e2e test in ``test_jarvis_webinfer_e2e.py`` spins up a real
``live_adapter`` aiohttp app. ``live_adapter.py`` does
``from memory_summarizer import SummarizerModel`` /
``from memory_store_client import MemoryStoreClient`` at module-load
time, so both modules must be on sys.path **before** any test module is
collected.
"""

import sys
from pathlib import Path

# conftest.py lives at services/webui/tests/conftest.py
# parents[0] = services/webui/tests
# parents[1] = services/webui
# parents[2] = services
# parents[3] = repo root
_REPO = Path(__file__).resolve().parents[3]
_WEBINFER = _REPO / "services" / "webinfer"
_WEBUI_SRC = _REPO / "services" / "webui" / "src"

for _p in (str(_WEBUI_SRC), str(_WEBINFER), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
