import bcrypt
import time, uuid
from jose import jwt, JWTError

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

def issue_jwt(payload: dict, secret: str, minutes: int) -> str:
    exp = int(time.time() + minutes * 60)
    to_encode = payload.copy()
    to_encode.update({"exp": exp, "jti": str(uuid.uuid4())})
    return jwt.encode(to_encode, secret, algorithm="HS256")

def decode_jwt(token: str, secret: str) -> dict | None:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except JWTError:
        return None
