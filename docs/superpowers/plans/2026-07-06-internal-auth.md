# Internal Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add internal login plus operator-owned customer access for the company operations trial.

**Architecture:** Keep auth logic in a small `services/auth.py` module and wire it into Flask with minimal route-layer changes. Store users in `data/users.json`; store customer ownership as `owner_username` on customer rows. Avoid broad `app.py` or frontend refactors.

**Tech Stack:** Flask sessions, Werkzeug password hashing, JSON storage through existing `services.storage`, Python `unittest`.

## Global Constraints

- `admin` can see all customers and all customer-scoped data.
- `operator` can only see and operate on customers they created.
- Passwords are hashed; plaintext passwords are never stored.
- `/api/health`, login/logout/me, `/login`, and static assets remain anonymous.
- Other main pages and business APIs require login.
- Out-of-scope customer access returns 404.
- No public registration, customer-transfer UI, feature permission matrix, or large refactor.

---

### Task 1: Auth Store And Password Verification

**Files:**
- Create: `services/auth.py`
- Create: `tests/test_auth.py`

**Interfaces:**
- Produces: `load_users(path: str) -> list[dict]`
- Produces: `create_user(path: str, username: str, password: str, role: str = "operator") -> dict`
- Produces: `authenticate_user(path: str, username: str, password: str) -> dict | None`

- [x] **Step 1: Write failing tests**

Add tests that create a user, assert `password_hash` is not the plaintext password, and authenticate with the right password only.

- [x] **Step 2: Run red test**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_auth.AuthStoreTests -v`
Expected: FAIL because `services.auth` does not exist.

- [x] **Step 3: Implement auth store**

Use `werkzeug.security.generate_password_hash` and `check_password_hash`. Store users through `load_json` / `save_json`.

- [x] **Step 4: Run green test**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_auth.AuthStoreTests -v`
Expected: PASS.

### Task 2: Flask Login Gate

**Files:**
- Modify: `app.py`
- Modify: `tests/test_auth.py`

**Interfaces:**
- Consumes: `authenticate_user(F_USERS, username, password)`
- Produces: `current_user() -> dict | None`
- Produces: `require_login()` as a Flask `before_request` gate
- Adds routes: `/login`, `/api/auth/login`, `/api/auth/logout`, `/api/auth/me`

- [x] **Step 1: Write failing route tests**

Add tests for anonymous `/api/health`, anonymous `/` redirecting to `/login`, anonymous `/api/clients` returning 401, successful login, and `/api/auth/me`.

- [x] **Step 2: Run red test**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_auth.AuthRouteTests -v`
Expected: FAIL because auth routes and gate are missing.

- [x] **Step 3: Implement minimal Flask auth**

Add `F_USERS`, `app.secret_key`, auth routes, `current_user`, and a `before_request` gate that exempts only anonymous routes.

- [x] **Step 4: Run green test**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_auth.AuthRouteTests -v`
Expected: PASS.

### Task 3: Customer Ownership Filtering

**Files:**
- Modify: `app.py`
- Modify: `tests/test_auth.py`

**Interfaces:**
- Produces: `can_access_client(client: dict) -> bool`
- Produces: `require_client_access(client_id: str) -> dict | None`
- Updates: `GET /api/clients`, `POST /api/clients`, `PUT /api/clients/<cid>`, `DELETE /api/clients/<cid>`

- [x] **Step 1: Write failing ownership tests**

Add tests that operator-created customers get `owner_username`, operators only list their own customers, cross-operator customer update returns 404, and admin lists all customers.

- [x] **Step 2: Run red test**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_auth.CustomerOwnershipTests -v`
Expected: FAIL because ownership is not enforced.

- [x] **Step 3: Implement customer ownership**

Filter client lists for operators. Set `owner_username` on create. Check ownership before update/delete.

- [x] **Step 4: Run green test**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_auth.CustomerOwnershipTests -v`
Expected: PASS.

### Task 4: Customer-Scoped API Guard And Content Attribution

**Files:**
- Modify: `app.py`
- Modify: `tests/test_auth.py`

**Interfaces:**
- Consumes: `require_client_access(client_id)`
- Updates: content generation article dict with `created_by`
- Guards core customer-scoped endpoints used by the Wednesday flow: groups, materials, content generation, raw records, daily insights, and platform crawl.

- [x] **Step 1: Write failing tests**

Add tests that an operator cannot call content generation for another operator's customer and that a generated article records `created_by`.

- [x] **Step 2: Run red test**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_auth.ContentOwnershipTests -v`
Expected: FAIL because content generation lacks ownership checks and attribution.

- [x] **Step 3: Implement scoped guards**

Use `require_client_access(cid)` at the start of customer-scoped handlers. Add `created_by` from `current_user()` in `/api/content/generate`.

- [x] **Step 4: Run green test**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_auth.ContentOwnershipTests -v`
Expected: PASS.

### Task 5: Admin Bootstrap Script And Full Verification

**Files:**
- Create: `scripts/create_user.py`
- Modify: `README.md`
- Test: `tests/test_auth.py`

**Interfaces:**
- Produces command: `.\.venv\Scripts\python.exe scripts\create_user.py --username admin --role admin`

- [x] **Step 1: Write failing bootstrap test**

Add a test that calls the script with a password argument in a temporary data dir and verifies a hashed admin user is created.

- [x] **Step 2: Run red test**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_auth.BootstrapUserTests -v`
Expected: FAIL because the script does not exist.

- [x] **Step 3: Implement script and docs**

Create the script with `--username`, `--role`, optional `--password`, and optional `--users-path`. If `--password` is omitted, prompt with `getpass`.

- [x] **Step 4: Run full verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_auth tests.test_app_core -v
.\run_tests.bat
```

Expected: auth tests, app core tests, and the full suite pass.

