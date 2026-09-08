"""Shared API envelope models."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    """Stable error contract returned by every active FastAPI route."""

    code: str
    message: str
    requestId: str
    details: Dict[str, Any] = Field(default_factory=dict)


class ArtifactReference(BaseModel):
    """Reference to an immutable local JSON artifact."""

    model_config = ConfigDict(extra="forbid")

    artifactId: str
    artifactType: str
    jobId: Optional[str] = None
    revision: int
    schemaVersion: int
    createdAt: str
    sha256: str
