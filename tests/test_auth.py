import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import ANY, patch

import app as geo_app
from services.auth import authenticate_user, create_user, load_users
from services.pattern_library import PatternLibrary


@contextmanager
def isolated_auth_app():
    original = {
        "F_CLIENTS": geo_app.F_CLIENTS,
        "F_GROUPS": getattr(geo_app, "F_GROUPS", None),
        "F_RAW_RECORDS": getattr(geo_app, "F_RAW_RECORDS", None),
        "F_CRAWL_JOBS": getattr(geo_app, "F_CRAWL_JOBS", None),
        "F_SETTINGS": geo_app.F_SETTINGS,
        "F_CONTENT_GENERATIONS": getattr(geo_app, "F_CONTENT_GENERATIONS", None),
        "F_MATERIALS_INDEX": getattr(geo_app, "F_MATERIALS_INDEX", None),
        "UPLOAD_FOLDER": getattr(geo_app, "UPLOAD_FOLDER", None),
        "MATERIAL_CACHE_FOLDER": getattr(geo_app, "MATERIAL_CACHE_FOLDER", None),
        "F_USERS": getattr(geo_app, "F_USERS", None),
        "F_USER_SETTINGS": getattr(geo_app, "F_USER_SETTINGS", None),
        "AUTH_DISABLED": geo_app.app.config.get("AUTH_DISABLED"),
        "ALLOW_PUBLIC_REGISTER": geo_app.app.config.get("ALLOW_PUBLIC_REGISTER"),
        "SECRET_KEY": geo_app.app.config.get("SECRET_KEY"),
    }
    with tempfile.TemporaryDirectory() as tmp:
        geo_app.F_CLIENTS = os.path.join(tmp, "clients.json")
        geo_app.F_GROUPS = os.path.join(tmp, "probe_groups.json")
        geo_app.F_RAW_RECORDS = os.path.join(tmp, "raw_records.json")
        geo_app.F_CRAWL_JOBS = os.path.join(tmp, "crawl_jobs.json")
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
        geo_app.app.config["ALLOW_PUBLIC_REGISTER"] = False
        geo_app.app.config["SECRET_KEY"] = "test-secret"
        try:
            yield tmp
        finally:
            geo_app.F_CLIENTS = original["F_CLIENTS"]
            for key in ["F_GROUPS", "F_RAW_RECORDS", "F_CRAWL_JOBS"]:
                if original[key] is None and hasattr(geo_app, key):
                    delattr(geo_app, key)
                else:
                    setattr(geo_app, key, original[key])
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
            if original["ALLOW_PUBLIC_REGISTER"] is None:
                geo_app.app.config.pop("ALLOW_PUBLIC_REGISTER", None)
            else:
                geo_app.app.config["ALLOW_PUBLIC_REGISTER"] = original["ALLOW_PUBLIC_REGISTER"]
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

    def test_register_is_disabled_by_default(self):
        with isolated_auth_app():
            client = geo_app.app.test_client()

            response = client.post(
                "/api/auth/register",
                json={"username": "new-operator", "password": "secret-pass"},
            )

            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.get_json()["error"], "registration_disabled")
            self.assertIsNone(authenticate_user(geo_app.F_USERS, "new-operator", "secret-pass"))
            self.assertIsNone(client.get("/api/auth/me").get_json()["user"])

    def test_register_creates_operator_and_logs_in_when_explicitly_enabled(self):
        with isolated_auth_app():
            geo_app.app.config["ALLOW_PUBLIC_REGISTER"] = True
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

    def test_register_rejects_duplicate_username_when_explicitly_enabled(self):
        with isolated_auth_app():
            geo_app.app.config["ALLOW_PUBLIC_REGISTER"] = True
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

    def test_login_page_hides_public_register_by_default(self):
        with isolated_auth_app():
            client = geo_app.app.test_client()

            page = client.get("/login").get_data(as_text=True)

            self.assertIn("loginForm", page)
            self.assertNotIn("registerForm", page)

    def test_login_page_shows_public_register_when_explicitly_enabled(self):
        with isolated_auth_app():
            geo_app.app.config["ALLOW_PUBLIC_REGISTER"] = True
            client = geo_app.app.test_client()

            page = client.get("/login").get_data(as_text=True)

            self.assertIn("loginForm", page)
            self.assertIn("registerForm", page)


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

    def test_crawl_worker_only_claims_jobs_for_logged_in_operator(self):
        with isolated_auth_app():
            create_user(geo_app.F_USERS, "alice", "secret-pass", role="operator")
            create_user(geo_app.F_USERS, "bob", "secret-pass", role="operator")
            create_user(geo_app.F_USERS, "admin", "secret-pass", role="admin")

            alice = geo_app.app.test_client()
            login_as(alice, "alice")
            alice_client = create_client(alice, "Alice 客户")
            created = alice.post("/api/crawl_jobs", json={
                "client_id": alice_client["id"],
                "platform": "qwen",
                "questions": ["Alice 问题"],
            })
            self.assertEqual(created.status_code, 200)
            job_id = created.get_json()["job"]["id"]

            bob = geo_app.app.test_client()
            login_as(bob, "bob")
            bob_jobs = bob.get("/api/crawl_jobs")
            self.assertEqual(bob_jobs.status_code, 200)
            self.assertEqual(bob_jobs.get_json()["jobs"], [])

            bob_cancel = bob.post(f"/api/crawl_jobs/{job_id}/cancel")
            self.assertEqual(bob_cancel.status_code, 404)

            bob_result = bob.post(f"/api/crawl_jobs/{job_id}/result", json={
                "status": "completed",
                "summary": {"total": 1, "success": 1},
                "results": [],
            })
            self.assertEqual(bob_result.status_code, 404)

            bob_claim = bob.get("/api/crawl_jobs/next?worker_id=bob-laptop&platform=qwen")
            self.assertEqual(bob_claim.status_code, 200)
            self.assertIsNone(bob_claim.get_json()["job"])

            admin = geo_app.app.test_client()
            login_as(admin, "admin")
            admin_jobs = admin.get("/api/crawl_jobs")
            self.assertEqual(admin_jobs.status_code, 200)
            self.assertEqual([job["id"] for job in admin_jobs.get_json()["jobs"]], [job_id])
            admin_claim = admin.get("/api/crawl_jobs/next?worker_id=admin-laptop&platform=qwen")
            self.assertEqual(admin_claim.status_code, 200)
            self.assertIsNone(admin_claim.get_json()["job"])

            alice_claim = alice.get("/api/crawl_jobs/next?worker_id=alice-laptop&platform=qwen")
            self.assertEqual(alice_claim.status_code, 200)
            self.assertEqual(alice_claim.get_json()["job"]["id"], job_id)


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
        with isolated_auth_app() as tmp:
            create_user(geo_app.F_USERS, "alice", "secret-pass", role="operator")
            client = geo_app.app.test_client()
            login_as(client, "alice")
            owned_client = create_client(client, "Alice 客户")
            library = PatternLibrary(Path(tmp) / "pattern_library")
            skeleton = library.create_candidate("global", "skeleton", "测试骨架", {"parent_type": "对比型", "sections": ["开头", "正文"]}, {"url": "seed://s"})
            library.set_status("global", skeleton["id"], "active")
            for name, kind in [("开头", "开头"), ("结尾", "结尾")]:
                entry = library.create_candidate("global", "module", name, {"type": kind, "pattern": name}, {"url": f"seed://{name}"})
                library.set_status("global", entry["id"], "active")
            brief = {
                "title_candidates": ["标题一", "标题二"], "angle_statement": "中性主线",
                "sections": [{"id": 1, "功能": "开头", "要点": "资料", "引用": [], "字数": 100}, {"id": 2, "功能": "正文", "要点": "资料", "引用": [], "字数": 300}],
                "bans": [], "dedup_hints": "",
            }

            with patch("app.pattern_library_service", return_value=library), \
                    patch("app.generate_planning_brief", return_value=brief), \
                    patch("app.ai_deepseek_pro", return_value="测试标题\n测试正文"):
                response = client.post(
                    "/api/content/generate",
                    json={"client_id": owned_client["id"], "opinion": "写一篇介绍"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["article"]["created_by"], "alice")

    def test_operator_gets_404_for_other_customer_content_configuration_materials_and_batch_job(self):
        with isolated_auth_app():
            for username, role in [("alice", "operator"), ("bob", "operator"), ("admin", "admin")]:
                create_user(geo_app.F_USERS, username, "secret-pass", role=role)
            bob = geo_app.app.test_client()
            login_as(bob, "bob")
            bob_client = create_client(bob, "Bob 客户")
            job = {"job_id": "bob-batch", "client_id": bob_client["id"], "status": "queued"}

            alice = geo_app.app.test_client()
            login_as(alice, "alice")
            with patch.object(geo_app, "get_content_batch_generation_job", return_value=job):
                responses = [
                    alice.post("/api/content/generate", json={"client_id": bob_client["id"]}),
                    alice.post("/api/content/generate_batch", json={"client_id": bob_client["id"], "count": 3}),
                    alice.get(f"/api/content/generate_batch/bob-batch"),
                    alice.post(f"/api/content/generate_batch/bob-batch/cancel"),
                    alice.get(f"/api/content/generations?client_id={bob_client['id']}"),
                    alice.get(f"/api/clients/{bob_client['id']}/content-options"),
                    alice.get(f"/api/groups/{bob_client['id']}"),
                    alice.get(f"/api/materials/{bob_client['id']}/package-result"),
                    alice.get(f"/api/raw_records?client_id={bob_client['id']}"),
                ]
            self.assertTrue(all(response.status_code == 404 for response in responses))

            admin = geo_app.app.test_client()
            login_as(admin, "admin")
            self.assertEqual(200, admin.get(f"/api/clients/{bob_client['id']}/content-options").status_code)
            with patch.object(geo_app, "get_content_batch_generation_job", return_value=job):
                self.assertEqual(200, admin.get("/api/content/generate_batch/bob-batch").status_code)

    def test_identifier_only_record_and_reference_jobs_enforce_customer_ownership(self):
        with isolated_auth_app():
            for username, role in [("alice", "operator"), ("bob", "operator"), ("admin", "admin")]:
                create_user(geo_app.F_USERS, username, "secret-pass", role=role)
            bob = geo_app.app.test_client()
            login_as(bob, "bob")
            bob_client = create_client(bob, "Bob 客户")
            geo_app.save(geo_app.F_RAW_RECORDS, [{"id": "bob-record", "client_id": bob_client["id"], "crawl_time": "2026-07-21 10:00"}])
            with geo_app.reference_analysis_jobs_guard:
                geo_app.reference_analysis_jobs.clear()
            status_job_id = geo_app.create_reference_analysis_job(bob_client["id"], "2026-07-21", username="bob")
            cancel_job_id = geo_app.create_reference_analysis_job(bob_client["id"], "2026-07-20", username="bob")

            alice = geo_app.app.test_client()
            login_as(alice, "alice")
            self.assertEqual(404, alice.delete("/api/daily/records/bob-record").status_code)
            self.assertEqual(404, alice.post("/api/daily/records/batch_delete", json={"ids": ["bob-record"]}).status_code)
            self.assertEqual(404, alice.get(f"/api/reference_intelligence/analyze_status?job_id={status_job_id}").status_code)
            self.assertEqual(404, alice.post("/api/reference_intelligence/analyze_cancel", json={"job_id": cancel_job_id}).status_code)

            admin = geo_app.app.test_client()
            login_as(admin, "admin")
            self.assertEqual(200, admin.get(f"/api/reference_intelligence/analyze_status?job_id={status_job_id}").status_code)
            self.assertEqual(200, admin.post("/api/reference_intelligence/analyze_cancel", json={"job_id": cancel_job_id}).status_code)

    def test_pattern_library_scopes_follow_client_ownership_and_shared_writes_require_admin(self):
        with isolated_auth_app() as tmp:
            for username, role in [("alice", "operator"), ("bob", "operator"), ("admin", "admin")]:
                create_user(geo_app.F_USERS, username, "secret-pass", role=role)
            bob = geo_app.app.test_client()
            login_as(bob, "bob")
            bob_client = create_client(bob, "Bob 客户")
            library = PatternLibrary(Path(tmp) / "pattern_library")
            client_entry = library.create_candidate(f"client:{bob_client['id']}", "module", "客户写法", {}, {"url": "https://example.com/client"})
            shared_entry = library.create_candidate("industry:education", "module", "行业写法", {}, {"url": "https://example.com/industry"})

            alice = geo_app.app.test_client()
            login_as(alice, "alice")
            with patch.object(geo_app, "pattern_library_service", return_value=library):
                self.assertEqual(404, alice.get(f"/api/pattern-library/entries?scope=client:{bob_client['id']}").status_code)
                self.assertEqual(200, alice.get("/api/pattern-library/entries?scope=industry:education").status_code)
                self.assertEqual(404, alice.post("/api/pattern-library/status", json={"scope": "industry:education", "entry_id": shared_entry["id"], "status": "active"}).status_code)

            admin = geo_app.app.test_client()
            login_as(admin, "admin")
            with patch.object(geo_app, "pattern_library_service", return_value=library):
                self.assertEqual(200, admin.get(f"/api/pattern-library/entries?scope=client:{bob_client['id']}").status_code)
                self.assertEqual(200, admin.post("/api/pattern-library/status", json={"scope": "industry:education", "entry_id": shared_entry["id"], "status": "active"}).status_code)


class UserSettingsTests(unittest.TestCase):
    def test_distribution_credentials_are_per_operator_and_not_returned(self):
        with isolated_auth_app():
            create_user(geo_app.F_USERS, "alice", "secret-pass", role="operator")
            create_user(geo_app.F_USERS, "bob", "secret-pass", role="operator")
            alice = geo_app.app.test_client()
            bob = geo_app.app.test_client()
            login_as(alice, "alice")
            login_as(bob, "bob")

            saved = alice.post("/api/distribution/credentials", json={
                "secret_id": "alice-id", "secret_key": "alice-key",
            })
            alice_status = alice.get("/api/distribution/credentials").get_json()
            bob_status = bob.get("/api/distribution/credentials").get_json()
            settings_status = alice.get("/api/settings").get_json()

            self.assertEqual(saved.status_code, 200)
            self.assertTrue(alice_status["configured"])
            self.assertNotIn("secret_id", alice_status)
            self.assertNotIn("secret_key", alice_status)
            self.assertNotIn("rwmeiti_secret_id", settings_status)
            self.assertNotIn("rwmeiti_secret_key", settings_status)
            self.assertFalse(bob_status["configured"])
            self.assertEqual(geo_app.load(geo_app.user_settings_path("alice"), {})["rwmeiti_secret_key"], "alice-key")

    def test_catalog_sync_saves_both_resource_types_per_operator(self):
        class FakeSupplier:
            def list_self_media(self, page, limit):
                return [{"resource_id": "7", "name": "账号A", "price": 88, "status": "1", "raw": {}}] if page == 1 else []

            def list_news_media(self, page, limit):
                return [{"resource_id": "8", "name": "媒体A", "price": 99, "status": "1", "raw": {}}] if page == 1 else []

        with isolated_auth_app() as tmp:
            original = getattr(geo_app, "F_DISTRIBUTION_CATALOG", None)
            geo_app.F_DISTRIBUTION_CATALOG = os.path.join(tmp, "distribution_catalog")
            try:
                result = geo_app.sync_distribution_catalog("alice", FakeSupplier())
                catalog = geo_app.load(geo_app.distribution_catalog_path("alice"), [])
                self.assertEqual(result["count"], 2)
                self.assertEqual(
                    [(item["resource_type"], item["resource_id"]) for item in catalog],
                    [("self_media", "7"), ("news_media", "8")],
                )
            finally:
                if original is None:
                    delattr(geo_app, "F_DISTRIBUTION_CATALOG")
                else:
                    geo_app.F_DISTRIBUTION_CATALOG = original

    def test_catalog_sync_links_an_existing_unique_name_only_favorite(self):
        class FakeSupplier:
            def list_self_media(self, page, limit):
                return [{"resource_id": "7", "name": "账号A", "price": 88, "status": "1", "raw": {}}] if page == 1 else []

            def list_news_media(self, page, limit):
                return []

        with isolated_auth_app() as tmp:
            original_catalog = getattr(geo_app, "F_DISTRIBUTION_CATALOG", None)
            original_favorites = geo_app.F_DISTRIBUTION_FAVORITES
            geo_app.F_DISTRIBUTION_CATALOG = os.path.join(tmp, "distribution_catalog")
            geo_app.F_DISTRIBUTION_FAVORITES = os.path.join(tmp, "distribution_favorites")
            try:
                geo_app.save(geo_app.distribution_favorites_path("alice"), [{"id": "favorite-a", "name": "账号A", "resource_id": ""}])

                geo_app.sync_distribution_catalog("alice", FakeSupplier())

                favorite = geo_app.load(geo_app.distribution_favorites_path("alice"), [])[0]
                self.assertEqual(favorite["resource_id"], "7")
                self.assertEqual(favorite["resource_type"], "self_media")
            finally:
                geo_app.F_DISTRIBUTION_FAVORITES = original_favorites
                if original_catalog is None:
                    delattr(geo_app, "F_DISTRIBUTION_CATALOG")
                else:
                    geo_app.F_DISTRIBUTION_CATALOG = original_catalog

    def test_favorite_is_added_from_catalog_and_refreshes_by_its_id(self):
        class FakeSupplier:
            def __init__(self):
                self.requests = []

            def list_self_media(self, page, limit, resource_id):
                self.requests.append((page, limit, resource_id))
                return [{"resource_id": resource_id, "name": "账号A", "price": 108, "status": "1", "raw": {}}]

        with isolated_auth_app() as tmp:
            original_catalog = getattr(geo_app, "F_DISTRIBUTION_CATALOG", None)
            original_favorites = geo_app.F_DISTRIBUTION_FAVORITES
            geo_app.F_DISTRIBUTION_CATALOG = os.path.join(tmp, "distribution_catalog")
            geo_app.F_DISTRIBUTION_FAVORITES = os.path.join(tmp, "distribution_favorites")
            try:
                create_user(geo_app.F_USERS, "alice", "secret-pass", role="operator")
                browser = geo_app.app.test_client()
                login_as(browser, "alice")
                geo_app.save(geo_app.distribution_catalog_path("alice"), [{
                    "resource_id": "7", "resource_type": "self_media", "name": "账号A", "price": 88, "status": "1", "raw": {},
                }])

                added = browser.post("/api/distribution/favorites", json={"resource_id": "7", "resource_type": "self_media"})
                supplier = FakeSupplier()
                with patch.object(geo_app, "rwmeiti_client_from_env", return_value=supplier):
                    refreshed = browser.post("/api/distribution/favorites/refresh")
                favorites = browser.get("/api/distribution/favorites").get_json()["favorites"]

                self.assertEqual(added.status_code, 200)
                self.assertEqual(refreshed.status_code, 200)
                self.assertEqual(supplier.requests, [(1, 5, "7")])
                self.assertEqual(favorites[0]["name"], "账号A")
                self.assertEqual(favorites[0]["price"], 108)
            finally:
                geo_app.F_DISTRIBUTION_FAVORITES = original_favorites
                if original_catalog is None:
                    delattr(geo_app, "F_DISTRIBUTION_CATALOG")
                else:
                    geo_app.F_DISTRIBUTION_CATALOG = original_catalog

    def test_cannot_add_favorite_not_in_current_operator_catalog(self):
        with isolated_auth_app() as tmp:
            original_catalog = getattr(geo_app, "F_DISTRIBUTION_CATALOG", None)
            geo_app.F_DISTRIBUTION_CATALOG = os.path.join(tmp, "distribution_catalog")
            try:
                create_user(geo_app.F_USERS, "alice", "secret-pass", role="operator")
                browser = geo_app.app.test_client()
                login_as(browser, "alice")

                response = browser.post("/api/distribution/favorites", json={"resource_id": "7", "resource_type": "self_media"})

                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.get_json()["error"], "catalog_resource_not_found")
            finally:
                if original_catalog is None:
                    delattr(geo_app, "F_DISTRIBUTION_CATALOG")
                else:
                    geo_app.F_DISTRIBUTION_CATALOG = original_catalog

    def test_match_operator_favorites_keeps_exact_candidates_and_resource_types(self):
        class FakeSupplier:
            def list_self_media(self, page, limit):
                return [{"resource_id": "7", "name": "账号A", "price": 88, "status": "1", "raw": {}}] if page == 1 else []

            def list_news_media(self, page, limit):
                return [{"resource_id": "8", "name": "媒体A", "price": 99, "status": "1", "resource_type": "news_media", "raw": {}}] if page == 1 else []

        with isolated_auth_app() as tmp:
            original_favorites = getattr(geo_app, "F_DISTRIBUTION_FAVORITES", None)
            original_jobs = getattr(geo_app, "F_DISTRIBUTION_MATCH_JOBS", None)
            geo_app.F_DISTRIBUTION_FAVORITES = os.path.join(tmp, "distribution_favorites")
            geo_app.F_DISTRIBUTION_MATCH_JOBS = os.path.join(tmp, "distribution_match_jobs")
            try:
                geo_app.save(geo_app.distribution_favorites_path("alice"), [
                    {"id": "a", "name": "账号A", "resource_id": ""},
                    {"id": "b", "name": "媒体A", "resource_id": ""},
                    {"id": "c", "name": "不存在", "resource_id": ""},
                ])

                geo_app.match_operator_favorites("alice", FakeSupplier())

                favorites = geo_app.load(geo_app.distribution_favorites_path("alice"), [])
                self.assertEqual(favorites[0]["candidates"][0]["resource_type"], "self_media")
                self.assertEqual(favorites[1]["candidates"][0]["resource_type"], "news_media")
                self.assertEqual(favorites[2]["candidates"], [])
            finally:
                if original_favorites is None:
                    delattr(geo_app, "F_DISTRIBUTION_FAVORITES")
                else:
                    geo_app.F_DISTRIBUTION_FAVORITES = original_favorites
                if original_jobs is None:
                    delattr(geo_app, "F_DISTRIBUTION_MATCH_JOBS")
                else:
                    geo_app.F_DISTRIBUTION_MATCH_JOBS = original_jobs

    def test_match_operator_favorites_preserves_list_edits_made_while_scanning(self):
        with isolated_auth_app() as tmp:
            original_favorites = getattr(geo_app, "F_DISTRIBUTION_FAVORITES", None)
            geo_app.F_DISTRIBUTION_FAVORITES = os.path.join(tmp, "distribution_favorites")
            try:
                geo_app.save(geo_app.distribution_favorites_path("alice"), [{"id": "a", "name": "账号A", "resource_id": ""}])

                class FakeSupplier:
                    def list_self_media(self, page, limit):
                        if page == 1:
                            geo_app.save(geo_app.distribution_favorites_path("alice"), [
                                {"id": "a", "name": "账号A", "resource_id": ""},
                                {"id": "b", "name": "后来添加", "resource_id": ""},
                            ])
                            return [{"resource_id": "7", "name": "账号A", "price": 88, "status": "1", "raw": {}}]
                        return []

                    def list_news_media(self, page, limit):
                        return []

                geo_app.match_operator_favorites("alice", FakeSupplier())

                self.assertEqual([item["name"] for item in geo_app.load(geo_app.distribution_favorites_path("alice"), [])], ["账号A", "后来添加"])
            finally:
                if original_favorites is None:
                    delattr(geo_app, "F_DISTRIBUTION_FAVORITES")
                else:
                    geo_app.F_DISTRIBUTION_FAVORITES = original_favorites

    def test_distribution_match_status_is_isolated_by_operator(self):
        with isolated_auth_app() as tmp:
            original_favorites = getattr(geo_app, "F_DISTRIBUTION_FAVORITES", None)
            original_jobs = getattr(geo_app, "F_DISTRIBUTION_MATCH_JOBS", None)
            geo_app.F_DISTRIBUTION_FAVORITES = os.path.join(tmp, "distribution_favorites")
            geo_app.F_DISTRIBUTION_MATCH_JOBS = os.path.join(tmp, "distribution_match_jobs")
            try:
                create_user(geo_app.F_USERS, "alice", "secret-pass", role="operator")
                create_user(geo_app.F_USERS, "bob", "secret-pass", role="operator")
                alice = geo_app.app.test_client()
                bob = geo_app.app.test_client()
                login_as(alice, "alice")
                login_as(bob, "bob")
                with patch.object(geo_app, "start_distribution_favorite_match", return_value={"status": "running"}, create=True) as start_match:
                    started = alice.post("/api/distribution/favorites/match")

                self.assertEqual(started.status_code, 202)
                start_match.assert_called_once_with("alice", ANY)
                self.assertEqual(bob.get("/api/distribution/favorites/match").get_json()["job"]["status"], "idle")
            finally:
                if original_favorites is None:
                    delattr(geo_app, "F_DISTRIBUTION_FAVORITES")
                else:
                    geo_app.F_DISTRIBUTION_FAVORITES = original_favorites
                if original_jobs is None:
                    delattr(geo_app, "F_DISTRIBUTION_MATCH_JOBS")
                else:
                    geo_app.F_DISTRIBUTION_MATCH_JOBS = original_jobs

    def test_distribution_favorites_are_isolated_by_operator(self):
        with isolated_auth_app() as tmp:
            original = getattr(geo_app, "F_DISTRIBUTION_FAVORITES", None)
            geo_app.F_DISTRIBUTION_FAVORITES = os.path.join(tmp, "distribution_favorites")
            try:
                create_user(geo_app.F_USERS, "alice", "secret-pass", role="operator")
                create_user(geo_app.F_USERS, "bob", "secret-pass", role="operator")
                alice = geo_app.app.test_client()
                bob = geo_app.app.test_client()
                login_as(alice, "alice")
                login_as(bob, "bob")

                added = alice.post("/api/distribution/favorites", json={"name": "账号A", "resource_id": "7"})

                self.assertEqual(added.status_code, 200)
                self.assertEqual([item["name"] for item in alice.get("/api/distribution/favorites").get_json()["favorites"]], ["账号A"])
                self.assertEqual(bob.get("/api/distribution/favorites").get_json()["favorites"], [])
            finally:
                if original is None:
                    delattr(geo_app, "F_DISTRIBUTION_FAVORITES")
                else:
                    geo_app.F_DISTRIBUTION_FAVORITES = original

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
