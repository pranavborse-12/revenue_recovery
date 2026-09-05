"""Health check endpoint."""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """
    Basic liveness check.

    Phase 1 keeps this simple: if the process can respond, it's healthy.
    We're not checking DB connectivity here yet -- a readiness probe that
    also verifies the database is reachable is a reasonable future
    addition, but isn't required for Phase 1's scope.
    """
    return HealthResponse(status="healthy")
