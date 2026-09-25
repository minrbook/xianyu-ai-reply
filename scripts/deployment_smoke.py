"""Run through stdin inside backend-web; no real Xianyu accounts or messages."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "/app/backend-web")
sys.path.insert(0, "/app")


def rejection_code(response):
    # The full application's legacy exception handlers wrap errors in HTTP 200.
    if response.status_code == 200:
        data = response.json()
        assert data.get("success") is False, "Expected explicit rejection"
        return data.get("code")
    return response.status_code


async def main():
    import httpx
    import common.models  # Register ORM mappings.
    from common.db.session import async_session_maker, async_engine
    from app.core.config import get_settings
    from app.services.auth import AuthService
    from app.services.jwt_secret_service import ensure_jwt_secret_key
    from common.utils.credential_crypto import encrypt_credential, decrypt_credential
    await ensure_jwt_secret_key(get_settings())
    async with async_session_maker() as session:
        service = AuthService(session)
        user, error = await service.authenticate_by_username("admin", Path("/run/secrets/admin_password").read_text().strip())
        assert user is not None, "Initial administrator authentication failed"
        access = service.create_access_token(user)
        refresh = service.create_refresh_token(user)
        await session.rollback()
    async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
        for endpoint in ("http://backend-web:8089/health", "http://websocket:8090/health", "http://scheduler:8091/health", "http://frontend/health"):
            assert (await client.get(endpoint)).status_code == 200, "Health check failed: " + endpoint
        endpoint = "http://backend-web:8089/api/v1/auth/verify"
        assert (await client.get(endpoint, headers={"Authorization": "Bearer " + access})).json()["authenticated"]
        assert not (await client.get(endpoint, headers={"Authorization": "Bearer " + refresh})).json()["authenticated"]
        payload = {"cookie_id": "deployment-smoke-nonexistent", "chat_id": "test", "to_user_id": "test", "message": "not sent"}
        endpoint = "http://backend-web:8089/api/v1/messages/send"
        assert rejection_code(await client.post(endpoint, json=payload)) in (401, 403)
        assert rejection_code(await client.post(endpoint, json=payload, headers={"Authorization": "Bearer " + access})) == 403
        assert rejection_code(await client.post("http://websocket:8090/password-login", json={})) in (401, 403)
    encrypted = encrypt_credential("deployment-smoke")
    assert encrypted.startswith("enc:v1:") and decrypt_credential(encrypted) == "deployment-smoke"
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()
        await page.goto("http://frontend/", wait_until="domcontentloaded")
        await page.wait_for_selector("input[type=password]", timeout=30000)
        assert await page.title()
        await browser.close()
    await async_engine.dispose()
    print("PASS: real MySQL/admin authentication, service health, JWT boundaries, message authorization, internal API protection, encryption, Chromium login page")


if __name__ == "__main__":
    asyncio.run(main())
