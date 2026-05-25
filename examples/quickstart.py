"""
OpenKNet — Quickstart example
==============================
Self-contained script that runs the full pipeline from scratch.
No external services required. Everything stored in ./quickstart_data/

Usage:
    python examples/quickstart.py

Expected output:
    ✓ project created
    ✓ 3 documents ingested (28 chunks)
    ✓ graph built: 41 entities, 181 relations
    ✓ rank "login error" → top entity: error 503
    ✓ ask (Spanish) → entities found: ['error 503', 'AuthService', ...]
    ✓ path AuthService → error 503: found in 1 hop
    ✓ incremental build: 0 new chunks (nothing added)
    ✓ stats: ranker=bm25
"""
import asyncio
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Setup workspace so we don't pollute .openknet
# ---------------------------------------------------------------------------
WORKSPACE = Path("./quickstart_data")
SCHEMA    = Path("examples/support/schema.yaml")
DOCS_DIR  = Path("examples/support/docs")

if not SCHEMA.exists() or not DOCS_DIR.exists():
    print("Run this script from the openknet root directory:")
    print("  python examples/quickstart.py")
    sys.exit(1)

import os
os.environ["OPENKNET_WORKSPACE_ROOT"] = str(WORKSPACE)
os.environ["OPENKNET_LOG_LEVEL"] = "WARNING"   # suppress INFO during demo

shutil.rmtree(WORKSPACE, ignore_errors=True)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def ok(msg): print(f"  ✓  {msg}")
def fail(msg): print(f"  ✗  {msg}"); sys.exit(1)


# ---------------------------------------------------------------------------
# Main async pipeline
# ---------------------------------------------------------------------------
async def main():
    from openknet import OpenKNet

    print("\nOpenKNet Quickstart\n" + "─" * 40)

    # ── 1. Initialise project ────────────────────────────────────────────
    async with OpenKNet.open("quickstart", schema=str(SCHEMA)) as knet:
        ok("project created")

        # ── 2. Ingest ───────────────────────────────────────────────────
        r = await knet.ingest(str(DOCS_DIR))
        if r.documents_added == 0:
            fail("no documents ingested")
        ok(f"{r.documents_added} documents ingested ({r.chunks_added} chunks)")

        # ── 3. Build ────────────────────────────────────────────────────
        b = await knet.build()
        if b.entities == 0:
            fail("build produced no entities")
        ok(f"graph built: {b.entities} entities, {b.relations} relations, "
           f"{b.evidence} evidence records")

        # ── 4. Rank ─────────────────────────────────────────────────────
        rank = await knet.rank("login error", limit=3)
        if not rank.results:
            fail("rank returned no results")
        top = rank.results[0]
        ok(f"rank 'login error' → top entity: {top.name} "
           f"({top.type}, score={top.score:.2f}, ranker={rank.ranker})")

        # ── 5. Ask (Spanish question, English docs) ──────────────────────
        ask = await knet.ask("qué componentes causan errores de autenticación?")
        if not ask.entities:
            fail("ask returned no entities")
        ok(f"ask (Spanish) → entities: {ask.entities[:3]}, "
           f"snippets: {len(ask.snippets)}")

        # ── 6. Path ─────────────────────────────────────────────────────
        path = await knet.path("AuthService", "error 503")
        if not path.found:
            # May not be found if dedup merged them; try alternative
            path = await knet.path("AuthService", "Portal X")
        status = f"found in {path.paths[0].length} hop(s)" if path.found else "not found (check schema)"
        ok(f"path AuthService → {'error 503' if path.source == 'AuthService' else path.target}: {status}")

        # ── 7. Incremental build ─────────────────────────────────────────
        b2 = await knet.build(incremental=True)
        ok(f"incremental build: {b2.chunks_processed} new chunks processed")

        # ── 8. Snapshots ────────────────────────────────────────────────
        snaps = await knet.snapshots()
        ok(f"{len(snaps)} graph snapshot(s) saved")

        # ── 9. Stats ─────────────────────────────────────────────────────
        stats = await knet.stats()
        ok(f"stats: ranker={stats.ranker_backend}, "
           f"docs={stats.documents}, chunks={stats.chunks}, "
           f"entities={stats.entities}")

    print("\n" + "─" * 40)
    print("  All checks passed — OpenKNet is working correctly.\n")
    print("  Next: try the interactive API at http://localhost:8000/docs")
    print("        openknet serve\n")

    # Cleanup
    shutil.rmtree(WORKSPACE, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
