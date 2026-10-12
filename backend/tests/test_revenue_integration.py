import os
import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import httpx
from jose import jwt
from sqlalchemy import text

from app.config import settings
from app.core.auth import clear_auth_cache
from app.core.database_pool import db_pool
from app.services.cache import redis_client


@unittest.skipUnless(os.getenv("RUN_REVENUE_INTEGRATION") == "1", "requires seeded PostgreSQL and Redis")
class RevenueIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_accounts_cache_boundaries_and_precision(self):
        from app.main import app

        await db_pool.initialize()
        suffix = uuid4().hex
        properties = [f"test-{suffix}-{zone}" for zone in ("paris", "new-york", "money", "mixed")]
        # Test credentials are supplied via the environment, not copied into source.
        accounts = [
            (os.environ["CLIENT_A_EMAIL"], os.environ["CLIENT_A_PASSWORD"], "tenant-a"),
            (os.environ["CLIENT_B_EMAIL"], os.environ["CLIENT_B_PASSWORD"], "tenant-b"),
        ]
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                tokens = {}
                for email, password, tenant in accounts:
                    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
                    self.assertEqual(login.status_code, 200, login.text)
                    tokens[tenant] = login.json()["access_token"]
                    identity = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens[tenant]}"})
                    self.assertEqual(identity.status_code, 200, identity.text)
                    self.assertEqual(identity.json()["tenant_id"], tenant)
                    wrong = await client.post("/api/v1/auth/login", json={"email": email, "password": "invalid"})
                    self.assertEqual(wrong.status_code, 401, wrong.text)

                async def summary(tenant, property_id="prop-001", **params):
                    return await client.get(
                        "/api/v1/dashboard/summary",
                        params={"property_id": property_id, **params},
                        headers={"Authorization": f"Bearer {tokens[tenant]}"},
                    )

                # Exercise real Redis misses and hits, warming in both client orders.
                await redis_client.delete("revenue:prop-001")
                for tenants in (("tenant-a", "tenant-b"), ("tenant-b", "tenant-a")):
                    for tenant in tenants:
                        await redis_client.delete("revenue:v2:" + json.dumps(
                            [tenant, "prop-001", None, None], separators=(",", ":"),
                        ))
                    for _ in range(2):
                        for tenant in tenants:
                            response = await summary(tenant)
                            self.assertEqual(response.status_code, 200, response.text)
                            self.assertEqual(response.json()["total_revenue_exact"],
                                             "2250.00" if tenant == "tenant-a" else "0.00")
                            self.assertEqual(response.json()["reservations_count"],
                                             4 if tenant == "tenant-a" else 0)
                            self.assertEqual(response.headers["Cache-Control"], "private, no-store")
                for tenant, foreign in (("tenant-a", "prop-004"), ("tenant-b", "prop-002")):
                    self.assertEqual((await summary(tenant, foreign)).status_code, 404)

                march = await summary("tenant-a", month=3, year=2024)
                self.assertEqual(march.status_code, 200, march.text)
                self.assertEqual(march.json()["total_revenue_exact"], "2250.00")
                self.assertEqual((await summary("tenant-a", month=2, year=2024)).json()["total_revenue_exact"], "0.00")

                async with db_pool.get_session() as session:
                    for property_id, zone in zip(properties, ("Europe/Paris", "America/New_York", "UTC", "UTC")):
                        await session.execute(text("""
                            INSERT INTO properties (id, tenant_id, name, timezone)
                            VALUES (:id, 'tenant-a', 'Regression fixture', :zone)
                        """), {"id": property_id, "zone": zone})
                    fixtures = [
                        (properties[0], "2024-02-29T22:59:59Z", "100.000", "USD"),
                        (properties[0], "2024-02-29T23:00:00Z", "1.005", "USD"),
                        (properties[0], "2024-03-31T21:59:59Z", "2.675", "USD"),
                        (properties[0], "2024-03-31T22:00:00Z", "100.000", "USD"),
                        (properties[1], "2024-03-01T04:59:59Z", "100.000", "USD"),
                        (properties[1], "2024-03-01T05:00:00Z", "10.000", "USD"),
                        (properties[1], "2024-04-01T03:59:59Z", "20.000", "USD"),
                        (properties[1], "2024-04-01T04:00:00Z", "100.000", "USD"),
                        (properties[2], "2024-03-01T00:00:00Z", "333.333", "USD"),
                        (properties[2], "2024-03-02T00:00:00Z", "333.333", "USD"),
                        (properties[2], "2024-03-03T00:00:00Z", "333.334", "USD"),
                        (properties[3], "2024-03-01T00:00:00Z", "10.000", "USD"),
                        (properties[3], "2024-03-02T00:00:00Z", "10.000", "EUR"),
                    ]
                    for index, (property_id, instant, amount, currency) in enumerate(fixtures):
                        check_in = datetime.fromisoformat(instant.replace("Z", "+00:00"))
                        await session.execute(text("""
                            INSERT INTO reservations
                            (id, property_id, tenant_id, check_in_date, check_out_date, total_amount, currency)
                            VALUES (:id, :property, 'tenant-a', :start, :end, :amount, :currency)
                        """), {
                            "id": f"test-{suffix}-{index}", "property": property_id,
                            "start": check_in, "end": check_in + timedelta(days=1),
                            "amount": Decimal(amount), "currency": currency,
                        })
                    await session.commit()

                for property_id, expected, count in zip(properties[:3], ("3.68", "30.00", "1000.00"), (2, 2, 3)):
                    for _ in range(2):
                        response = await summary("tenant-a", property_id, month=3, year=2024)
                        self.assertEqual(response.status_code, 200, response.text)
                        self.assertEqual(response.json()["total_revenue_exact"], expected)
                        self.assertEqual(response.json()["total_revenue"], float(expected))
                        self.assertEqual(response.json()["reservations_count"], count)
                    self.assertEqual((await summary("tenant-b", property_id, month=3, year=2024)).status_code, 404)
                self.assertEqual((await summary("tenant-a", properties[3])).status_code, 422)
                self.assertEqual((await summary("tenant-a", month=3)).status_code, 422)
                self.assertEqual((await summary("tenant-a", month=13, year=2024)).status_code, 422)
                self.assertEqual((await client.get("/api/v1/dashboard/summary", params={"property_id": "prop-001"})).status_code, 401)

                payload = {
                    "id": "unknown", "email": "unknown@example.com", "aud": "authenticated",
                    "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
                    "user_metadata": {"tenant_id": "tenant-a"},
                }
                for signing_key in (settings.secret_key, "not-the-signing-key"):
                    forged = jwt.encode(payload, signing_key, algorithm="HS256")
                    response = await client.get("/api/v1/dashboard/summary", params={"property_id": "prop-001"},
                                                headers={"Authorization": f"Bearer {forged}"})
                    self.assertIn(response.status_code, (401, 403), response.text)

                # Warm the cache, then ensure token expiry is still enforced.
                short_lived = jwt.encode({
                    **payload, "app_metadata": {"tenant_id": "tenant-a"},
                    "exp": datetime.now(timezone.utc) + timedelta(seconds=2),
                }, settings.secret_key, algorithm="HS256")
                headers = {"Authorization": f"Bearer {short_lived}"}
                response = await client.get("/api/v1/dashboard/summary", params={"property_id": "prop-001"}, headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                await asyncio.sleep(2)
                response = await client.get("/api/v1/dashboard/summary", params={"property_id": "prop-001"}, headers=headers)
                self.assertEqual(response.status_code, 401, response.text)

                expired = jwt.encode({
                    **payload, "app_metadata": {"tenant_id": "tenant-a"},
                    "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
                }, settings.secret_key, algorithm="HS256")
                response = await client.get("/api/v1/dashboard/summary", params={"property_id": "prop-001"},
                                            headers={"Authorization": f"Bearer {expired}"})
                self.assertEqual(response.status_code, 401, response.text)
        finally:
            async with db_pool.get_session() as session:
                await session.execute(text("DELETE FROM reservations WHERE property_id = ANY(:ids)"), {"ids": properties})
                await session.execute(text("DELETE FROM properties WHERE id = ANY(:ids)"), {"ids": properties})
                await session.commit()
            clear_auth_cache()
            for property_id in properties:
                for month, year in ((None, None), (3, 2024)):
                    await redis_client.delete("revenue:v2:" + json.dumps(
                        ["tenant-a", property_id, year, month], separators=(",", ":"),
                    ))
            await redis_client.aclose()
            await db_pool.close()


if __name__ == "__main__":
    unittest.main()
