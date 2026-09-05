"""Firebase ID-token verification for protected API routes."""

from functools import lru_cache
from threading import Lock

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_db
from app.models.organization import Organization
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)
_firebase_initialization_lock = Lock()
_user_provisioning_lock = Lock()
logger = get_logger(__name__)


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
        logger.warning("Firebase ID token verification failed (%s): %s", type(exc).__name__, exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_organization_id(
    firebase_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> int:
    """Resolve the verified Firebase identity to an app-level Organization.

    Firebase only proves *who* the caller is; it says nothing about which
    merchant organization they belong to. That mapping lives in our own
    `users` table (keyed by email, the one claim we can rely on Firebase
    to have verified). A first-time caller gets a private organization so
    authenticated users do not fail after sign-in, while existing users
    continue to resolve to their assigned organization.
    """
    email = firebase_user.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated identity has no email claim to resolve an organization",
        )

    email = email.strip().lower()
    with _user_provisioning_lock:
        app_user = db.scalars(select(User).where(func.lower(User.email) == email)).first()
        if app_user is None:
            organization_name = f"Workspace for {email}"
            organization = db.scalars(
                select(Organization).where(Organization.name == organization_name)
            ).first()
            if organization is None:
                organization = Organization(name=organization_name)
                db.add(organization)
                try:
                    db.flush()
                except IntegrityError:
                    db.rollback()
                    organization = db.scalars(
                        select(Organization).where(Organization.name == organization_name)
                    ).one()

            app_user = User(email=email, organization_id=organization.id, role="admin")
            db.add(app_user)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                app_user = db.scalars(
                    select(User).where(func.lower(User.email) == email)
                ).one()

    return app_user.organization_id