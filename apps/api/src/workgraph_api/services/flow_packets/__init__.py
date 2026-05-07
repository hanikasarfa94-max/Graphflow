"""Flow Packet projection — internal package.

The public entry point is `FlowProjectionService` in
`workgraph_api.services.flow_projection`. This package holds the
decomposed building blocks (contracts, visibility, sorting,
participants, per-recipe projectors) that the facade orchestrates.

See `docs/flow-packets-spec.md` for the projection model and
`docs/architecture-organization.md §Phase A` for why this package
exists. Read order for new contributors:

  1. `contracts.py`   — packet contract factories + type literals
  2. `visibility.py`  — viewer-side gating, bucket selection
  3. `projectors/`    — one file per recipe; each exposes a single
                        `derive_*` async function
  4. `participants.py`— sidecar resolver
  5. The facade in `flow_projection.py`

Internals are not part of the public API. Import from
`workgraph_api.services` for `FlowProjectionService` only.
"""
from __future__ import annotations
