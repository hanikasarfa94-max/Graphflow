from __future__ import annotations

import logging
import sys

from workgraph_observability import configure_logging


def boot(argv: list[str] | None = None) -> int:
    configure_logging("INFO")
    log = logging.getLogger("workgraph.worker")
    log.info("worker boot ok — Celery wiring lands in Phase 6+")
    return 0


if __name__ == "__main__":
    sys.exit(boot(sys.argv[1:]))
