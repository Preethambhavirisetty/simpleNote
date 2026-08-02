import bcrypt


def hash_password(password: str) -> str:
    password_bytes = password.encode('utf-8')
    password_hash = bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds=12))
    return password_hash.decode('utf-8')

def check_password(password: str, password_hashed: str) -> bool:
    password_bytes = password.encode('utf-8')
    password_hashed_bytes = password_hashed.encode('utf-8')
    return bcrypt.checkpw(password_bytes, password_hashed_bytes)
