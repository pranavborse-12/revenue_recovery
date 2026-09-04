"""Firebase ID-token verification for protected API routes."""

from functools import lru_cache
from threading import Lock

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

bearer_scheme = HTTPBearer(auto_error=False)
_firebase_initialization_lock = Lock()


@lru_cache(maxsize=1)
def _firebase_app():
    settings = get_settings()
    if not all((settings.FIREBASE_PROJECT_ID, settings.FIREBASE_CLIENT_EMAIL, settings.FIREBASE_PRIVATE_KEY)):
        return None

    try:
        import firebase_admin
        from firebase_admin import credentials
    except ModuleNotFoundError as exc:
        raise RuntimeError("firebase-admin must be installed to protect the API") from exc

    # FastAPI runs synchronous dependencies in a thread pool.  On the first
    # requests after startup, two threads can otherwise both observe an empty
    # Firebase registry and try to create the default app.
    with _firebase_initialization_lock:
        if firebase_admin._apps:
            return firebase_admin.get_app()

        credential = credentials.Certificate(
            {
                "type": "service_account",
                "project_id": settings.FIREBASE_PROJECT_ID,
                "private_key": settings.FIREBASE_PRIVATE_KEY.replace("\\n", "\n"),
                "client_email": settings.FIREBASE_CLIENT_EMAIL,
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        )
        return firebase_admin.initialize_app(credential)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """Require and verify a Firebase ID token for protected API access."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    app = _firebase_app()
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is not configured",
        )

    try:
        from firebase_admin import auth

        return auth.verify_id_token(credentials.credentials, app=app)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
