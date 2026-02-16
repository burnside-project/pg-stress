from app.verifiers.cache_memory import CacheMemoryVerifier
from app.verifiers.wal_checkpoints import WALCheckpointsVerifier
from app.verifiers.locks import LocksVerifier
from app.verifiers.replication import ReplicationVerifier

VERIFIER_REGISTRY = {
    "cache-memory": CacheMemoryVerifier,
    "wal-checkpoints": WALCheckpointsVerifier,
    "locks": LocksVerifier,
    "replication": ReplicationVerifier,
}
