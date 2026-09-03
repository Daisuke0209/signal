from sqlalchemy import text

from signal_api.database import SessionLocal


def main() -> None:
    with SessionLocal() as db:
        row = db.execute(
            text(
                "SELECT current_database() AS database_name, current_user AS user_name"
            )
        ).one()

    print("Database connection succeeded:")
    print({"database_name": row.database_name, "user_name": row.user_name})


if __name__ == "__main__":
    main()
