import asyncio
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException

from app.config import Settings
from app.jsonl_reader import JSONLReader
from app.models import VerificationResult
from app.pg_client import PGClient
from app.report import write_reports
from app.verifiers import VERIFIER_REGISTRY
from app.verifiers.cache_memory import CacheMemoryVerifier
from app.verifiers.locks import LocksVerifier
from app.verifiers.replication import ReplicationVerifier
from app.verifiers.wal_checkpoints import WALCheckpointsVerifier

settings = Settings()

pg_client: PGClient | None = None
jsonl_reader: JSONLReader | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pg_client, jsonl_reader
    dsn = (
        f"postgresql://{settings.pg_user}:{settings.pg_password}"
        f"@{settings.pg_host}:{settings.pg_port}/{settings.pg_database}"
    )
    pg_client = PGClient(dsn)
    await pg_client.connect()
    jsonl_reader = JSONLReader(
        settings.collector_output_path,
        settings.collector_database_id,
    )
    yield
    await pg_client.close()


app = FastAPI(title="truth-service", lifespan=lifespan)


def _get_verifier(panel: str):
    """Instantiate the verifier for a given panel name."""
    if panel == "cache-memory":
        return CacheMemoryVerifier(pg_client, jsonl_reader, settings)
    elif panel == "wal-checkpoints":
        return WALCheckpointsVerifier()
    elif panel == "locks":
        return LocksVerifier()
    elif panel == "replication":
        return ReplicationVerifier()
    return None


@app.get("/verify/{panel}")
async def verify_panel(panel: str) -> VerificationResult:
    verifier = _get_verifier(panel)
    if verifier is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown panel: {panel}. Available: {list(VERIFIER_REGISTRY.keys())}",
        )
    return await verifier.verify()


@app.get("/panels")
async def list_panels():
    return {"panels": list(VERIFIER_REGISTRY.keys())}


@app.get("/health")
async def health():
    return {"status": "ok"}


async def cli_verify(panel: str):
    """Run a single verification in CLI mode and write reports."""
    global pg_client, jsonl_reader

    dsn = (
        f"postgresql://{settings.pg_user}:{settings.pg_password}"
        f"@{settings.pg_host}:{settings.pg_port}/{settings.pg_database}"
    )
    pg_client = PGClient(dsn)
    await pg_client.connect()
    jsonl_reader = JSONLReader(
        settings.collector_output_path,
        settings.collector_database_id,
    )

    verifier = _get_verifier(panel)
    if verifier is None:
        print(f"Unknown panel: {panel}. Available: {list(VERIFIER_REGISTRY.keys())}")
        await pg_client.close()
        sys.exit(1)

    result = await verifier.verify()
    write_reports(result, settings.report_output_path)

    await pg_client.close()

    print(f"Panel:   {result.panel}")
    print(f"Verdict: {result.verdict}")
    print(f"Reports: {settings.report_output_path}/report.json")
    print(f"         {settings.report_output_path}/report.md")

    if result.assertions:
        print()
        for a in result.assertions:
            status = "PASS" if a.passed else "FAIL"
            print(f"  [{status}] {a.metric}: {a.detail}")

    if result.errors:
        print()
        for e in result.errors:
            print(f"  [ERROR] {e}")

    sys.exit(0 if result.verdict == "PASS" else 1)


if __name__ == "__main__":
    if settings.cli_mode:
        panel = sys.argv[1] if len(sys.argv) > 1 else "cache-memory"
        asyncio.run(cli_verify(panel))
    else:
        uvicorn.run(app, host=settings.host, port=settings.port)