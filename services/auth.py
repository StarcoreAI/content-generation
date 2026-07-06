from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from services.storage import load_json, save_json


VALID_ROLES = {"admin", "operator"}


def load_users(path):
    users = load_json(path, [])
    return users if isinstance(users, list) else []


def find_user(path, username):
    username = str(username or "").strip()
    for user in load_users(path):
        if user.get("username") == username:
            return user
    return None


def create_user(path, username, password, role="operator"):
    username = str(username or "").strip()
    role = role if role in VALID_ROLES else "operator"
    if not username:
        raise ValueError("username is required")
    if not password:
        raise ValueError("password is required")
    if find_user(path, username):
        raise ValueError("user already exists")

    users = load_users(path)
    user = {
        "username": username,
        "password_hash": generate_password_hash(password),
        "role": role,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "disabled": False,
    }
    users.append(user)
    save_json(path, users)
    return user


def authenticate_user(path, username, password):
    user = find_user(path, username)
    if not user or user.get("disabled"):
        return None
    if not check_password_hash(user.get("password_hash", ""), password or ""):
        return None
    return user
