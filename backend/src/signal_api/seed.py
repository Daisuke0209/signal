import uuid

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from signal_api.config import get_settings
from signal_api.database import SessionLocal
from signal_api.models import Membership, MembershipRole, Organization, User
from signal_api.security import hash_password


def seed_demo_data(db: Session, password: str) -> tuple[uuid.UUID, uuid.UUID]:
    password_hash = hash_password(password)

    organization_id = db.execute(
        insert(Organization)
        .values(name="Signal Demo", slug="signal-demo")
        .on_conflict_do_update(
            index_elements=[Organization.slug],
            set_={"name": "Signal Demo"},
        )
        .returning(Organization.id)
    ).scalar_one()

    user_id = db.execute(
        insert(User)
        .values(
            name="Demo User",
            email="demo@signal.local",
            password_hash=password_hash,
        )
        .on_conflict_do_update(
            index_elements=[User.email],
            set_={
                "name": "Demo User",
                "password_hash": password_hash,
            },
        )
        .returning(User.id)
    ).scalar_one()

    db.execute(
        insert(Membership)
        .values(
            organization_id=organization_id,
            user_id=user_id,
            role=MembershipRole.ADMIN,
        )
        .on_conflict_do_update(
            index_elements=[Membership.organization_id, Membership.user_id],
            set_={"role": MembershipRole.ADMIN},
        )
    )

    return organization_id, user_id


def main() -> None:
    settings = get_settings()
    if settings.seed_demo_password is None:
        raise RuntimeError("SEED_DEMO_PASSWORD is required")

    with SessionLocal.begin() as db:
        seed_demo_data(db, settings.seed_demo_password.get_secret_value())

    print("Demo data seeded:")
    print("- organization: signal-demo")
    print("- user: demo@signal.local")
    print("- role: admin")


if __name__ == "__main__":
    main()
