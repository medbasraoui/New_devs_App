import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.api.v1.dashboard import get_dashboard_summary
from app.core.tenant_resolver import TenantResolver
from app.services import cache, reservations
from redis.exceptions import ConnectionError as RedisConnectionError


class RevenueTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_isolates_shared_property_ids_in_both_orders(self):
        for tenants in (("tenant-a", "tenant-b"), ("tenant-b", "tenant-a")):
            stored = {"revenue:prop-001": json.dumps({
                "property_id": "prop-001", "tenant_id": tenants[0],
                "total": "999.00", "currency": "USD", "count": 1,
            })}

            async def get(key):
                return stored.get(key)

            async def setex(key, ttl, value):
                stored[key] = value

            async def calculate(property_id, tenant_id, **kwargs):
                return {
                    "property_id": property_id, "tenant_id": tenant_id,
                    "total": "2250.00" if tenant_id == "tenant-a" else "0.00",
                    "currency": "USD", "count": 4 if tenant_id == "tenant-a" else 0,
                }

            with (
                patch.object(cache.redis_client, "get", side_effect=get),
                patch.object(cache.redis_client, "setex", side_effect=setex),
                patch.object(reservations, "calculate_total_revenue", side_effect=calculate) as query,
            ):
                for _ in range(2):
                    for tenant in tenants:
                        result = await cache.get_revenue_summary("prop-001", tenant)
                        self.assertEqual(result["tenant_id"], tenant)
                        self.assertEqual(result["total"], "2250.00" if tenant == "tenant-a" else "0.00")
                self.assertEqual(query.call_count, 2)

    async def test_dashboard_fails_closed_without_tenant(self):
        with patch("app.api.v1.dashboard.get_revenue_summary", new_callable=AsyncMock) as query:
            with self.assertRaises(HTTPException) as caught:
                await get_dashboard_summary("prop-001", SimpleNamespace(tenant_id=None))
            self.assertEqual(caught.exception.status_code, 403)
            query.assert_not_awaited()

    async def test_cache_rejects_mismatched_owner(self):
        with patch.object(cache.redis_client, "get", new_callable=AsyncMock, return_value=json.dumps({
            "property_id": "prop-001", "tenant_id": "tenant-b", "total": "99.00",
        })):
            with self.assertRaises(HTTPException) as caught:
                await cache.get_revenue_summary("prop-001", "tenant-a")
            self.assertEqual(caught.exception.status_code, 503)

    async def test_cache_failure_does_not_return_fabricated_revenue(self):
        with patch("app.api.v1.dashboard.get_revenue_summary", side_effect=RedisConnectionError("unavailable")):
            with self.assertRaises(HTTPException) as caught:
                await get_dashboard_summary("prop-001", SimpleNamespace(tenant_id="tenant-a"))
            self.assertEqual(caught.exception.status_code, 503)

    async def test_database_failure_does_not_return_fabricated_revenue(self):
        with patch.object(reservations.db_pool, "initialize", side_effect=OSError("unavailable")):
            with self.assertRaises(OSError):
                await reservations.calculate_total_revenue("prop-001", "tenant-a")

    def test_round_only_after_summing_subcent_amounts(self):
        amounts = [Decimal("333.333"), Decimal("333.333"), Decimal("333.334")]
        self.assertEqual(reservations.round_revenue(sum(amounts)), Decimal("1000.00"))
        self.assertEqual(reservations.round_revenue(Decimal("-1.005")), Decimal("-1.01"))

    async def test_numeric_contract_and_exact_half_up_rounding(self):
        for amount, expected in (("1.005", "1.01"), ("2.675", "2.68"), ("-1.005", "-1.01")):
            with patch("app.api.v1.dashboard.get_revenue_summary", new_callable=AsyncMock) as query:
                query.return_value = {
                    "property_id": "prop-001", "tenant_id": "tenant-a",
                    "total": amount, "currency": "USD", "count": 1,
                }
                result = await get_dashboard_summary("prop-001", SimpleNamespace(tenant_id="tenant-a"))
                self.assertIsInstance(result["total_revenue"], float)
                self.assertEqual(result["total_revenue"], float(expected))
                self.assertEqual(result["total_revenue_exact"], expected)

    async def test_unmapped_user_is_not_assigned_to_tenant_a(self):
        with self.assertRaises(HTTPException) as caught:
            await TenantResolver.resolve_tenant_id("unknown", "unknown@example.com")
        self.assertEqual(caught.exception.status_code, 403)

    def test_user_editable_metadata_cannot_select_tenant(self):
        self.assertEqual(TenantResolver.resolve_tenant_from_user({
            "app_metadata": {"tenant_id": "tenant-a"},
            "user_metadata": {"tenant_id": "tenant-b"},
        }), "tenant-a")
        self.assertIsNone(TenantResolver.resolve_tenant_from_user({
            "user_metadata": {"tenant_id": "tenant-b"},
        }))

    async def test_monthly_calculation_is_not_a_zero_placeholder(self):
        with patch.object(reservations, "calculate_total_revenue", new_callable=AsyncMock) as query:
            query.return_value = {"total": "2250.00"}
            result = await reservations.calculate_monthly_revenue("prop-001", 3, 2024, tenant_id="tenant-a")
            self.assertEqual(result, Decimal("2250.00"))


class MonthBoundaryTests(unittest.TestCase):
    def test_paris_march_uses_different_dst_offsets(self):
        self.assertEqual(reservations.month_boundaries(3, 2024, "Europe/Paris"), (
            datetime(2024, 2, 29, 23, tzinfo=timezone.utc),
            datetime(2024, 3, 31, 22, tzinfo=timezone.utc),
        ))

    def test_new_york_march_uses_different_dst_offsets(self):
        self.assertEqual(reservations.month_boundaries(3, 2024, "America/New_York"), (
            datetime(2024, 3, 1, 5, tzinfo=timezone.utc),
            datetime(2024, 4, 1, 4, tzinfo=timezone.utc),
        ))

    def test_december_rolls_over_year(self):
        start, end = reservations.month_boundaries(12, 2024, "UTC")
        self.assertEqual(start, datetime(2024, 12, 1, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2025, 1, 1, tzinfo=timezone.utc))

    def test_invalid_month_is_rejected(self):
        with self.assertRaises(ValueError):
            reservations.month_boundaries(13, 2024, "UTC")


if __name__ == "__main__":
    unittest.main()
