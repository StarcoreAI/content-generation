import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import app as geo_app
from services.auth import authenticate_user, create_user, load_users


@contextmanager
def isolated_auth_app():
    original = {
        "F_CLIENTS": geo_app.F_CLIENTS,
        "F_SETTINGS": geo_app.F_SETTINGS,
        "F_CONTENT_GENERATIONS": getattr(geo_app, "F_CONTENT_GENERATIONS", None),
        "F_MATERIALS_INDEX": getattr(geo_app, "F_MATERIALS_INDEX", None),
        "UPLOAD_FOLDER": getattr(geo_app, "UPLOAD_FOLDER", None),
        "MATERIAL_CACHE_FOLDER": getattr(geo_app, "MATERIAL_CACHE_FOLDER", None),
        "F_USERS": getattr(geo_app, "F_USERS", None),
        "F_USER_SETTINGS": getattr(geo_app, "F_USER_SETTINGS", None),
        "AUTH_DISABLED": geo_app.app.config.get("AUTH_DISABLED"),
        "SECRET_KEY": geo_app.app.config.get("SECRET_KEY"),
    }
    with tempfile.TemporaryDirectory() as tmp:
        geo_app.F_CLIENTS = os.path.join(tmp, "clients.json")
        geo_app.F_SETTINGS = os.path.join(tmp, "settings.json")
        geo_app.F_CONTENT_GENERATIONS = os.path.join(tmp, "content_generations.json")
        if hasattr(geo_app, "F_MATERIALS_INDEX"):
            geo_app.F_MATERIALS_INDEX = os.path.join(tmp, "materials_index.json")
        if hasattr(geo_app, "UPLOAD_FOLDER"):
            geo_app.UPLOAD_FOLDER = os.path.join(tmp, "uploads")
        if hasattr(geo_app, "MATERIAL_CACHE_FOLDER"):
            geo_app.MATERIAL_CACHE_FOLDER = os.path.join(tmp, "material_cache")
        geo_app.F_USERS = os.path.join(tmp, "users.json")
        geo_app.F_USER_SETTINGS = os.path.join(tmp, "user_settings")
        geo_app.app.config["AUTH_DISABLED"] = False
        geo_app.app.config["SECRET_KEY"] = "test-secret"
        try:
            yield tmp
        finally:
            geo_app.F_CLIENTS = original["F_CLIENTS"]
            geo_app.F_SETTINGS = original["F_SETTINGS"]
            if original["F_CONTENT_GENERATIONS"] is None and hasattr(geo_app, "F_CONTENT_GENERATIONS"):
                delattr(geo_app, "F_CONTENT_GENERATIONS")
            else:
                geo_app.F_CONTENT_GENERATIONS = original["F_CONTENT_GENERATIONS"]
            for key in ["F_MATERIALS_INDEX", "UPLOAD_FOLDER", "MATERIAL_CACHE_FOLDER"]:
                if original[key] is None and hasattr(geo_app, key):
                    delattr(geo_app, key)
                else:
                    setattr(geo_app, key, original[key])
            if original["F_USERS"] is None and hasattr(geo_app, "F_USERS"):
                delattr(geo_app, "F_USERS")
            else:
                geo_app.F_USERS = original["F_USERS"]
            if original["F_USER_SETTINGS"] is None and hasattr(geo_app, "F_USER_SETTINGS"):
                delattr(geo_app, "F_USER_SETTINGS")
            else:
                geo_app.F_USER_SETTINGS = original["F_USER_SETTINGS"]
            if original["AUTH_DISABLED"] is None:
                geo_app.app.config.pop("AUTH_DISABLED", None)
            else:
                geo_app.app.config["AUTH_DISABLED"] = original["AUTH_DISABLED"]
            geo_app.app.config["SECRET_KEY"] = original["SECRET_KEY"]


class AuthStoreTests(unittest.TestCase):
    def test_create_user_hashes_password_and_authenticates(self):
        with tempfile.TemporaryDirectory() as tmp:
            users_path = os.path.join(tmp, "users.json")

            user = create_user(users_path, "alice", "secret-pass", role="operator")

            self.assertEqual(user["username"], "alice")
            self.assertEqual(user["role"], "operator")
            self.assertNotEqual(user["password_hash"], "secret-pass")
            self.assertEqual(load_users(users_path)[0]["username"], "alice")
            self.assertIsNotNone(authenticate_user(users_path, "alice", "secret-pass"))
            self.assertIsNone(authenticate_user(users_path, "alice", "wrong-pass"))


class AuthRouteTests(unittest.TestCase):
    def test_health_stays_public_but_page_and_api_require_login(self):
        with isolated_auth_app():
            client = geo_app.app.test_client()

            health = client.get("/api/health")
            self.assertEqual(health.status_code, 200)

            page = client.get("/")
            self.assertEqual(page.status_code, 302)
            self.assertIn("/login", page.headers["Location"])

            api = client.get("/api/clients")
            self.assertEqual(api.status_code, 401)
            self.assertEqual(api.get_json()["error"], "auth_required")

    def test_login_logout_and_current_user(self):
        with isolated_auth_app():
            create_user(geo_app.F_USERS, "alice", "secret-pass", role="operator")
            client = geo_app.app.test_client()

            bad = client.post("/api/auth/login", json={"username": "alice", "password": "bad"})
            self.assertEqual(bad.status_code, 401)

            good = client.post("/api/auth/login", json={"username": "alice", "password": "secret-pass"})
            self.assertEqual(good.status_code, 200)
            self.assertEqual(good.get_json()["user"]["username"], "alice")
            self.assertNotIn("password_hash", good.get_json()["user"])

            me = client.get("/api/auth/me")
            self.assertEqual(me.status_code, 200)
            self.assertEqual(me.get_json()["user"]["role"], "operator")

            logout = client.post("/api/auth/logout")
            self.assertEqual(logout.status_code, 200)
            self.assertIsNone(client.get("/api/auth/me").get_json()["user"])

    def test_register_creates_operator_and_logs_in(self):
        with isolated_auth_app():
            client = geo_app.app.test_client()

            response = client.post(
                "/api/auth/register",
                json={"username": "new-operator", "password": "secret-pass"},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["user"]["username"], "new-operator")
            self.assertEqual(payload["user"]["role"], "operator")
            self.assertNotIn("password_hash", payload["user"])
            self.assertEqual(client.get("/api/auth/me").get_json()["user"]["username"], "new-operator")
            self.assertIsNotNone(authenticate_user(geo_app.F_USERS, "new-operator", "secret-pass"))

    def test_register_rejects_duplicate_username(self):
        with isolated_auth_app():
            create_user(geo_app.F_USERS, "alice", "secret-pass", role="operator")
            client = geo_app.app.test_client()

            response = client.post(
                "/api/auth/register",
                json={"username": "alice", "password": "new-pass"},
            )

            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.get_json()["error"], "user_exists")
            self.assertIsNone(authenticate_user(geo_app.F_USERS, "alice", "new-pass"))
            self.assertIsNotNone(authenticate_user(geo_app.F_USERS, "alice", "secret-pass"))


def login_as(client, username, password="secret-pass"):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    if response.status_code != 200:
        raise AssertionError(response.get_data(as_text=True))
    return response


def create_client(client, name):
    response = client.post(
        "/api/clients",
        json={"name": name, "brand": name, "industry": "测试行业", "goal": ""},
    )
    if response.status_code != 200:
        raise AssertionError(response.get_data(as_text=True))
    return response.get_json()["client"]


class CustomerOwnershipTests(unittest.TestCase):
    def test_operator_created_customers_are_owned_and_filtered(self):
        with isolated_auth_app():
            create_user(geo_app.F_USERS, "alice", "secret-pass", role="operator")
            create_user(geo_app.F_USERS, "bob", "secret-pass", role="operator")
            create_user(geo_app.F_USERS, "admin", "secret-pass", role="admin")

            alice = geo_app.app.test_client()
            login_as(alice, "alice")
            alice_client = create_client(alice, "Alice 客户")
            self.assertEqual(alice_client["owner_username"], "alice")

            bob = geo_app.app.test_client()
            login_as(bob, "bob")
            bob_client = create_client(bob, "Bob 客户")
            self.assertEqual(bob_client["owner_username"], "bob")
            self.assertEqual([c["name"] for c in bob.get("/api/clients").get_json()], ["Bob 客户"])

            denied = bob.put(f"/api/clients/{alice_client['id']}", json={"name": "偷改"})
            self.assertEqual(denied.status_code, 404)

            admin = geo_app.app.test_client()
            login_as(admin, "admin")
            self.assertEqual(
                sorted(c["name"] for c in admin.get("/api/clients").get_json()),
                ["Alice 客户", "Bob 客户"],
            )


class ContentOwnershipTests(unittest.TestCase):
    def test_operator_cannot_generate_for_another_operator_customer(self):
        with isolated_auth_app():
            create_user(geo_app.F_USERS, "alice", "secret-pass", role="operator")
            create_user(geo_app.F_USERS, "bob", "secret-pass", role="operator")

            alice = geo_app.app.test_client()
            login_as(alice, "alice")
            alice_client = create_client(alice, "Alice 客户")

            bob = geo_app.app.test_client()
            login_as(bob, "bob")
            with patch("app.ai_deepseek_pro", return_value="标题\n正文"):
                denied = bob.post(
                    "/api/content/generate",
                    json={"client_id": alice_client["id"], "opinion": "写一篇介绍"},
                )
            self.assertEqual(denied.status_code, 404)

    def test_content_generation_records_created_by(self):
        with isolated_auth_app():
            create_user(geo_app.F_USERS, "alice", "secret-pass", role="operator")
            client = geo_app.app.test_client()
            login_as(client, "alice")
            owned_client = create_client(client, "Alice 客户")

            with patch("app.ai_deepseek_pro", return_value="测试标题\n测试正文"):
                response = client.post(
                    "/api/content/generate",
                    json={"client_id": owned_client["id"], "opinion": "写一篇介绍"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["article"]["created_by"], "alice")


class UserSettingsTests(unittest.TestCase):
    def test_user_settings_override_global_without_affecting_other_users(self):
        with isolated_auth_app():
            geo_app.save(geo_app.F_SETTINGS, {
                "api_key": "global-key",
                "base_url": "https://global.example.com",
                "model": "global-model",
                "preset": "global",
            })
            create_user(geo_app.F_USERS, "alice", "secret-pass", role="operator")
            create_user(geo_app.F_USERS, "bob", "secret-pass", role="operator")

            alice = geo_app.app.test_client()
            login_as(alice, "alice")
            saved = alice.post("/api/settings", json={
                "api_key": "alice-key",
                "base_url": "https://alice.example.com",
                "model": "alice-model",
                "preset": "alice",
            })
            self.assertEqual(saved.status_code, 200)

            bob = geo_app.app.test_client()
            login_as(bob, "bob")
            bob_settings = bob.get("/api/settings").get_json()
            self.assertEqual(bob_settings["base_url"], "https://global.example.com")
            self.assertEqual(bob_settings["model"], "global-model")
            self.assertTrue(bob_settings["has_key"])

            bob.post("/api/settings", json={
                "api_key": "bob-key",
                "base_url": "https://bob.example.com",
                "model": "bob-model",
            })

            self.assertEqual(alice.get("/api/settings").get_json()["model"], "alice-model")
            self.assertEqual(bob.get("/api/settings").get_json()["model"], "bob-model")
            self.assertEqual(geo_app.get_settings("alice")["api_key"], "alice-key")
            self.assertEqual(geo_app.get_settings("bob")["api_key"], "bob-key")
            self.assertEqual(geo_app.get_settings()["api_key"], "global-key")

    def test_new_user_settings_inherit_global_defaults(self):
        with isolated_auth_app():
            geo_app.save(geo_app.F_SETTINGS, {
                "api_key": "global-key",
                "base_url": "https://global.example.com",
                "model": "global-model",
            })
            create_user(geo_app.F_USERS, "alice", "secret-pass", role="operator")
            client = geo_app.app.test_client()
            login_as(client, "alice")

            payload = client.get("/api/settings").get_json()

            self.assertEqual(payload["base_url"], "https://global.example.com")
            self.assertEqual(payload["model"], "global-model")
            self.assertTrue(payload["has_key"])


class BootstrapUserTests(unittest.TestCase):
    def test_create_user_script_writes_hashed_admin(self):
        with tempfile.TemporaryDirectory() as tmp:
            users_path = os.path.join(tmp, "users.json")
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/create_user.py",
                    "--users-path",
                    users_path,
                    "--username",
                    "admin",
                    "--role",
                    "admin",
                    "--password",
                    "admin-pass",
                ],
                cwd=os.getcwd(),
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            users = load_users(users_path)
            self.assertEqual(users[0]["username"], "admin")
            self.assertEqual(users[0]["role"], "admin")
            self.assertNotEqual(users[0]["password_hash"], "admin-pass")
            self.assertIsNotNone(authenticate_user(users_path, "admin", "admin-pass"))
