import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
from supabase_auth.errors import AuthApiError

from app.api.v1 import login
from app.config import settings, Settings
from app.core.auth import authenticate_request, clear_auth_cache


class AuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        clear_auth_cache()

    async def test_non_fixture_login_verifies_password(self):
        auth = Mock()
        auth.sign_in_with_password.side_effect = AuthApiError("Invalid credentials", 400, "invalid_credentials")
        with patch.object(login, "supabase", SimpleNamespace(auth=auth)):
            with self.assertRaises(HTTPException) as caught:
                await login.login(login.LoginRequest(email="other@example.com", password="wrong"))
            self.assertEqual(caught.exception.status_code, 401)
            auth.sign_in_with_password.assert_called_once_with({"email": "other@example.com", "password": "wrong"})
            auth.admin.list_users.assert_not_called()

    async def test_signed_token_without_expiry_is_rejected(self):
        token = jwt.encode({
            "id": "test", "email": "test@example.com", "aud": "authenticated",
            "app_metadata": {"tenant_id": "tenant-a"},
        }, settings.secret_key, algorithm="HS256")
        with self.assertRaises(HTTPException) as caught:
            await authenticate_request(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))
        self.assertEqual(caught.exception.status_code, 401)

    async def test_unsigned_and_wrongly_signed_tokens_are_rejected(self):
        payload = {
            "id": "test", "email": "test@example.com", "aud": "authenticated",
            "app_metadata": {"tenant_id": "tenant-a"},
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        }
        for token in (
            jwt.encode(payload, "wrong-key", algorithm="HS256"),
            jwt.encode(payload, settings.secret_key, algorithm="HS256").rsplit(".", 1)[0] + ".",
        ):
            with self.assertRaises(HTTPException) as caught:
                await authenticate_request(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))
            self.assertEqual(caught.exception.status_code, 401)

    def test_production_rejects_public_development_signing_key(self):
        with self.assertRaises(ValueError):
            Settings(environment="production", secret_key="debug_challenge_secret")

