"""Lightweight Streamlit authentication and client selection."""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

import streamlit as st


SESSION_USER_KEY = "scry_user"
SESSION_CLIENT_KEY = "scry_client_id"


@dataclass(frozen=True)
class AuthenticatedUser:
    """Authenticated Scry user and active client context."""

    username: str
    display_name: str
    client_id: str
    client_name: str


def _to_plain_dict(value) -> dict:
    """Convert Streamlit secrets mapping objects into ordinary dictionaries."""

    if value is None:
        return {}

    return {
        key: _to_plain_dict(item) if hasattr(item, "items") else item
        for key, item in dict(value).items()
    }


def get_users_config() -> dict:
    """Return configured users from Streamlit secrets."""

    return _to_plain_dict(st.secrets.get("users", {}))


def get_clients_config() -> dict:
    """Return configured clients from Streamlit secrets."""

    return _to_plain_dict(st.secrets.get("clients", {}))


def hash_password(password: str, *, salt: str | None = None, iterations: int = 260_000) -> str:
    """Return a PBKDF2-SHA256 password hash suitable for Streamlit secrets."""

    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a plaintext password against a stored PBKDF2-SHA256 hash."""

    try:
        algorithm, iterations, salt, expected_hash = stored_hash.split("$", 3)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    actual_hash = hash_password(password, salt=salt, iterations=int(iterations)).split("$", 3)[3]
    return hmac.compare_digest(actual_hash, expected_hash)


def get_client_name(client_id: str) -> str:
    """Return a display name for a client id."""

    client_config = get_clients_config().get(client_id, {})
    return str(client_config.get("name") or client_id)


def get_current_user() -> AuthenticatedUser | None:
    """Return the current Streamlit session user, if one is authenticated."""

    user = st.session_state.get(SESSION_USER_KEY)
    client_id = st.session_state.get(SESSION_CLIENT_KEY)

    if not user or not client_id:
        return None

    return AuthenticatedUser(
        username=user["username"],
        display_name=user["display_name"],
        client_id=client_id,
        client_name=get_client_name(client_id),
    )


def set_current_user(username: str, display_name: str, client_id: str) -> None:
    """Persist an authenticated user in Streamlit session state."""

    st.session_state[SESSION_USER_KEY] = {
        "username": username,
        "display_name": display_name,
    }
    st.session_state[SESSION_CLIENT_KEY] = client_id


def logout() -> None:
    """Clear the current authenticated session."""

    st.session_state.pop(SESSION_USER_KEY, None)
    st.session_state.pop(SESSION_CLIENT_KEY, None)


def authenticate(username: str, password: str) -> AuthenticatedUser | None:
    """Authenticate a configured user and return their client context."""

    user_config = get_users_config().get(username)

    if not user_config:
        return None

    password_hash = str(user_config.get("password_hash", ""))
    client_id = str(user_config.get("client_id", ""))

    if not password_hash or not client_id or not verify_password(password, password_hash):
        return None

    display_name = str(user_config.get("name") or username)
    set_current_user(username, display_name, client_id)

    return AuthenticatedUser(
        username=username,
        display_name=display_name,
        client_id=client_id,
        client_name=get_client_name(client_id),
    )


def ensure_authenticated() -> AuthenticatedUser | None:
    """Render login UI when needed and return the active user context."""

    configured_users = get_users_config()

    if not configured_users:
        set_current_user("local", "Local development", "local")
        st.info("No users are configured. Running in local development mode.")
        return get_current_user()

    current_user = get_current_user()
    if current_user:
        return current_user

    st.title("Scry")
    st.subheader("Sign in")

    with st.form("scry_login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", use_container_width=True)

    if submitted:
        authenticated_user = authenticate(username.strip(), password)
        if authenticated_user:
            st.rerun()

        st.error("Invalid username or password.")

    return None
