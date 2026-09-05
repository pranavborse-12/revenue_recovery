from app.core.auth import get_current_organization_id
from app.models.organization import Organization
from app.models.user import User


def test_first_authenticated_identity_gets_private_workspace(db_session):
    firebase_user = {"email": "Owner@Example.com"}

    organization_id = get_current_organization_id(firebase_user, db_session)

    user = db_session.query(User).one()
    organization = db_session.query(Organization).one()
    assert organization_id == organization.id
    assert user.email == "owner@example.com"
    assert user.organization_id == organization.id

    assert get_current_organization_id(firebase_user, db_session) == organization.id
    assert db_session.query(Organization).count() == 1


def test_existing_workspace_is_reused(db_session):
    organization = Organization(name="Workspace for owner@example.com")
    db_session.add(organization)
    db_session.flush()
    db_session.add(User(email="owner@example.com", organization_id=organization.id, role="admin"))
    db_session.commit()

    organization_id = get_current_organization_id({"email": "OWNER@example.com"}, db_session)

    assert organization_id == organization.id
    assert db_session.query(Organization).count() == 1
    assert db_session.query(User).count() == 1