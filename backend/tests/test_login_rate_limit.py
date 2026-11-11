"""Sign-in is rate-limited per client address and per account, without revealing which accounts exist."""

from backend_test_helpers import DEMO_PASSWORD


def _login(client, email, password):
    return client.post("/api/auth/demo-login", json={"email": email, "password": password})


def test_failed_sign_ins_lock_the_account_for_a_while(client):
    auth = client.app.state.ctx.auth
    auth.login_failures.per_key = 3
    for _ in range(3):
        assert _login(client, "viewer@fl-healthcare.demo", "wrong-password-1").status_code == 401
    blocked = _login(client, "viewer@fl-healthcare.demo", DEMO_PASSWORD)  # even the right password waits
    assert blocked.status_code == 429 and "Too many sign-in attempts" in blocked.json()["detail"]
    # Another account is not affected.
    assert _login(client, "admin@fl-healthcare.demo", DEMO_PASSWORD).status_code == 200


def test_unknown_emails_get_the_same_answer(client):
    auth = client.app.state.ctx.auth
    auth.login_failures.per_key = 2
    for _ in range(2):
        assert _login(client, "nobody@example.org", "whatever-123").status_code == 401
    assert _login(client, "nobody@example.org", "whatever-123").json()["detail"] == _login(
        client, "nobody@example.org", "whatever-123"
    ).json()["detail"]
    assert _login(client, "nobody@example.org", "whatever-123").status_code == 429


def test_attempts_per_address(client):
    auth = client.app.state.ctx.auth
    auth.login_attempts.per_key = 4
    for _ in range(4):
        _login(client, "admin@fl-healthcare.demo", DEMO_PASSWORD)
    assert _login(client, "admin@fl-healthcare.demo", DEMO_PASSWORD).status_code == 429
