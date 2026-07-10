# Internal Auth And Customer Ownership Design

Date: 2026-07-06

## Goal

Add the minimum account and customer-ownership layer needed for an internal operations trial.

This is not an external SaaS permission system. It only needs to prevent operators from seeing or editing each other's customers while letting an admin account inspect everything for testing and support.

## Roles

- `admin`: can see all customers and all customer-scoped data.
- `operator`: can only see and operate on customers they created.

Each user has an independent username and password. Passwords are stored as hashes, never plaintext.

## User Storage

Store users in `data/users.json`.

User fields:

- `username`
- `password_hash`
- `role`: `admin` or `operator`
- `created_at`
- `disabled`: optional boolean, default false

The first admin is created by a small bootstrap command or helper, not by exposing an unauthenticated public signup flow.

## Customer Ownership

Add `owner_username` to each customer record in `data/clients.json`.

Ownership rules:

- When an operator creates a customer, `owner_username` is set to the current username.
- Operators only receive customers where `owner_username` matches their username.
- Operators can only read or mutate records for their own customers.
- Admins bypass ownership filtering and can see all customers.
- If an old customer has no `owner_username`, treat it as admin-visible only until assigned.

No customer-transfer UI is required in the first version. If needed later, add an admin-only owner update endpoint.

## Authentication

Use Flask session authentication.

Anonymous routes:

- `/login`
- `/api/auth/login`
- `/api/auth/logout`
- `/api/auth/me`
- `/api/health`
- static assets

All other main pages and business APIs require login.

`SECRET_KEY` should come from an environment variable in deployment. Local development may use a development fallback.

## API Behavior

Unauthenticated browser page requests redirect to `/login`.

Unauthenticated API requests return:

```json
{
  "error": "auth_required",
  "message": "请先登录"
}
```

with HTTP 401.

Customer-scoped API requests for a customer outside the current operator's ownership return HTTP 404, not a cross-user data leak.

## Content Generation Attribution

Content generation records include:

- `created_by`: current username if logged in

Existing listing order and article-type history isolation remain unchanged.

## Non-Goals

- Public registration creates non-admin operator accounts only.
- No per-feature permission matrix.
- No department or tenant hierarchy.
- No customer transfer UI in the first version.
- No large refactor of `app.py` or `templates/index.html`.

## Test Coverage

Add focused tests for:

- `/api/health` remains anonymous.
- `/` redirects to `/login` when anonymous.
- business APIs reject anonymous requests.
- login succeeds with a hashed-password user.
- operator-created customers are owned by that operator.
- operators cannot list or access each other's customers.
- admin can list all customers.
- content generation records `created_by`.
