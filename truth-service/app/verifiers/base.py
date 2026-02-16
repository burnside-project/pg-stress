from abc import ABC, abstractmethod
from app.models import VerificationResult


class BaseVerifier(ABC):
    """Abstract base for metric verifiers."""

    @property
    @abstractmethod
    def panel_name(self) -> str:
        """Name of the verification panel (e.g. 'cache-memory')."""

    @abstractmethod
    async def verify(self) -> VerificationResult:
        """Execute verification and return structured result."""