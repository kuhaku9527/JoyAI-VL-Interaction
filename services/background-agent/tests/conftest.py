# SPDX-License-Identifier: Apache-2.0
"""Make the hermes_api package importable for isolated unit tests."""

from __future__ import annotations

import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]  # services/background-agent
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))
