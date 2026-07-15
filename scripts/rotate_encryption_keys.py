"""Re-encrypt protected columns with ENCRYPTION_ACTIVE_KEY_ID.

Runs as a dry run by default. Use ``--apply`` only after all old keys and the
new active key are present in ENCRYPTION_KEYS. Any unreadable value aborts the
transaction so ciphertext is never overwritten or treated as plaintext.
"""

import argparse

from database import SessionLocal
from models import RecipeIngredient, User
from security import EncryptionError, needs_rotation, rotate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    db = SessionLocal()
    changed = 0
    try:
        for user in db.query(User).yield_per(500):
            for field in ("email", "phone"):
                value = getattr(user, field)
                if value and needs_rotation(value):
                    setattr(user, field, rotate(value))
                    changed += 1
        for ingredient in db.query(RecipeIngredient).yield_per(500):
            for field in ("name", "amount"):
                value = getattr(ingredient, field)
                if value and needs_rotation(value):
                    setattr(ingredient, field, rotate(value))
                    changed += 1
        if args.apply:
            db.commit()
            print(f"rotated {changed} encrypted values")
        else:
            db.rollback()
            print(f"dry run: {changed} encrypted values need rotation")
    except EncryptionError:
        db.rollback()
        raise
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
