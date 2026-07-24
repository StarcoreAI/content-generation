# Operator Distribution Credentials Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each operator save their own RWMeiti `secret_id` and `secret_key` from the distribution-resource page, then use the existing favorite matcher to find supplier resource IDs without exposing credentials.

**Architecture:** Reuse the existing per-user `data/user_settings/<username>.json` storage that `rwmeiti_client_from_env()` already reads. A dedicated distribution-credentials route returns only configuration booleans, never either credential; the resource page adds a small credential card and continues to use the existing candidate-match/sync flow.

**Tech Stack:** Flask, JSON files, vanilla JavaScript, unittest.

## Global Constraints

- Credentials are per operator, never global.
- GET responses and browser JavaScript must never contain saved `secret_id` or `secret_key`.
- Do not alter AI system-settings behavior or add a secret-management dependency.
- Keep manual ID input only as a fallback; supplier matching remains the normal way to acquire IDs.
- Do not commit work; the user requested direct workspace changes.

---

### Task 1: Add secret-safe per-operator distribution credential APIs

**Files:**
- Modify: `app.py:615-626, before /api/distribution/resources/sync`
- Test: `tests/test_auth.py`

**Interfaces:**
- `GET /api/distribution/credentials` returns `{ok, configured, base_url}` only.
- `POST /api/distribution/credentials` accepts `secret_id`, `secret_key`, and optional `base_url`; blank or `***` values preserve a saved credential.

- [ ] **Step 1: Write the failing test**

```python
saved = alice.post('/api/distribution/credentials', json={
    'secret_id': 'alice-id', 'secret_key': 'alice-key',
})
payload = alice.get('/api/distribution/credentials').get_json()
self.assertTrue(payload['configured'])
self.assertNotIn('secret_id', payload)
self.assertNotIn('secret_key', payload)
self.assertFalse(bob.get('/api/distribution/credentials').get_json()['configured'])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_auth.UserSettingsTests.test_distribution_credentials_are_per_operator_and_not_returned -v`

Expected: 404 because the route does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
@app.route('/api/distribution/credentials', methods=['GET', 'POST'])
def distribution_credentials_route():
    username = settings_username()
    if not username:
        return jsonify({'error': 'operator_not_found'}), 400
    settings = load(user_settings_path(username), {})
    if request.method == 'POST':
        for key in ('rwmeiti_secret_id', 'rwmeiti_secret_key'):
            value = str((request.get_json(silent=True) or {}).get(key.replace('rwmeiti_', '')) or '')
            if value and value != '***': settings[key] = value
        save(user_settings_path(username), settings)
    return jsonify({'ok': True, 'configured': bool(settings.get('rwmeiti_secret_id') and settings.get('rwmeiti_secret_key')), 'base_url': settings.get('rwmeiti_base_url') or DEFAULT})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_auth.UserSettingsTests.test_distribution_credentials_are_per_operator_and_not_returned -v`

Expected: PASS.

### Task 2: Add the operator-facing credentials card and clarify ID acquisition

**Files:**
- Modify: `templates/index.html:499`
- Modify: `static/js/app.js:45-140`
- Test: `tests/test_content_generation_ui.py`

**Interfaces:**
- `loadDistributionCredentials()` fetches only the safe status endpoint.
- `saveDistributionCredentials()` posts values from password inputs and clears them on success.
- `loadResourcePage()` invokes `loadDistributionCredentials()`.

- [ ] **Step 1: Write the failing UI test**

```python
template = (ROOT / 'templates' / 'index.html').read_text(encoding='utf-8')
script = (ROOT / 'static' / 'js' / 'app.js').read_text(encoding='utf-8')
self.assertIn('distributionSecretId', template)
self.assertIn('distributionSecretKey', template)
self.assertIn('loadDistributionCredentials', script)
self.assertIn('/api/distribution/credentials', script)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_content_generation_ui.ContentGenerationUiTests.test_resource_page_has_per_operator_distribution_credentials -v`

Expected: FAIL because the card and JavaScript do not exist.

- [ ] **Step 3: Write minimal implementation**

```javascript
async function saveDistributionCredentials() {
  const secret_id = document.getElementById('distributionSecretId').value.trim();
  const secret_key = document.getElementById('distributionSecretKey').value.trim();
  const r = await api('/api/distribution/credentials', 'POST', {secret_id, secret_key});
  if (r.error) return toast(r.error, 'err');
  document.getElementById('distributionSecretId').value = '';
  document.getElementById('distributionSecretKey').value = '';
  loadDistributionCredentials();
}
```

Place the fields in the distribution-resource page, use `type="password"`, and label the existing direct-ID card as a fallback after supplier matching.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m unittest tests.test_content_generation_ui.ContentGenerationUiTests.test_resource_page_has_per_operator_distribution_credentials -v; node --check static/js/app.js`

Expected: PASS.

### Task 3: Full verification

**Files:**
- Modify only files from Tasks 1-2.

- [ ] **Step 1: Run verification**

Run: `git diff --check; ./.venv/Scripts/python.exe -m py_compile app.py; ./.venv/Scripts/python.exe -m unittest tests.test_auth.UserSettingsTests tests.test_distribution_routes tests.test_content_generation_ui -v; node --check static/js/app.js`

Expected: exit code 0, apart from existing CRLF warnings.

## Self-review

- Credentials are scoped by authenticated username and are not sent back to the browser.
- Existing supplier matching supplies candidates and a one-click sync action, so IDs are no longer an expected manual input.
- No short-video behavior, global credential setting, or real supplier request is introduced.
