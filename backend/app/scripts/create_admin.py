"""Create a Stonic Console admin, or reset one's password (and switch it back on).

    python -m app.scripts.create_admin --email you@stonic.site --password "at-least-10-chars" --name "Your Name"

Run it from backend/ with DATABASE_URL pointing at the database to change
(your local one, or Render's External Database URL with ?ssl=require).
Running it again for the same email sets the new password, which is also the
way back in if every admin is locked out.
"""
import argparse
import asyncio

from fastapi import HTTPException

from app.db.session import SessionLocal
from app.modules.platform.admins import ensure_admin


async def main(email: str, password: str, name: str | None) -> None:
    async with SessionLocal() as db:
        admin, created = await ensure_admin(db, email=email, password=password, full_name=name)
    action = "Created" if created else "Updated the password of"
    print(f"{action} Stonic admin {admin.email}. Sign in at /console/login on the dashboard.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create or reset a Stonic Console admin")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True, help="at least 10 characters")
    parser.add_argument("--name", default=None)
    args = parser.parse_args()
    try:
        asyncio.run(main(args.email, args.password, args.name))
    except HTTPException as exc:
        raise SystemExit(f"Error: {exc.detail}")