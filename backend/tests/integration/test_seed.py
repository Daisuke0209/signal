import bcrypt
from sqlalchemy import func, select

from signal_api.config import get_settings
from signal_api.database import SessionLocal
from signal_api.models import Membership, MembershipRole, Organization, User
from signal_api.seed import seed_demo_data


def test_seed_is_idempotent_and_hashes_the_password() -> None:
    password_setting = get_settings().seed_demo_password
    assert password_setting is not None
    password = password_setting.get_secret_value()

    with SessionLocal() as db:
        transaction = db.begin()
        try:
            first_ids = seed_demo_data(db, password)
            second_ids = seed_demo_data(db, password)

            assert first_ids == second_ids

            organization_count = db.scalar(
                select(func.count())
                .select_from(Organization)
                .where(Organization.slug == "signal-demo")
            )
            user_count = db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.email == "demo@signal.local")
            )
            assert organization_count == 1
            assert user_count == 1

            organization_id, user_id = first_ids
            membership = db.get(
                Membership,
                {
                    "organization_id": organization_id,
                    "user_id": user_id,
                },
            )
            assert membership is not None
            assert membership.role is MembershipRole.ADMIN

            password_hash = db.scalar(
                select(User.password_hash).where(User.id == user_id)
            )
            assert password_hash is not None
            assert password_hash != password
            assert bcrypt.checkpw(password.encode(), password_hash.encode())
        finally:
            transaction.rollback()
