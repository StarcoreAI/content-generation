import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.auth import create_user


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create a GEO Agent user.")
    parser.add_argument("--users-path", default="data/users.json")
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", choices=["admin", "operator"], default="operator")
    parser.add_argument("--password")
    args = parser.parse_args(argv)

    password = args.password or getpass.getpass("Password: ")
    user = create_user(args.users_path, args.username, password, role=args.role)
    print(f"created {user['role']} user: {user['username']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
