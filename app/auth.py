import bcrypt
from fastapi import Request, Depends
from sqlalchemy.orm import Session

from models import get_db, User


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))


def get_current_user(request: Request, db: Session = Depends(get_db)):
    """
    Returns the logged-in User object, or None if no one is logged in.
    Reads the user id out of the signed session cookie (set at login).
    """
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()
