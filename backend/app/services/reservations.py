from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database_pool import db_pool


def month_boundaries(month: int, year: int, property_timezone: str) -> Tuple[datetime, datetime]:
    zone = ZoneInfo(property_timezone)
    start = datetime(year, month, 1, tzinfo=zone)
    end = datetime(year + 1, 1, 1, tzinfo=zone) if month == 12 else datetime(year, month + 1, 1, tzinfo=zone)
    # Convert each local midnight independently: DST may change within the month.
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def round_revenue(amount: Decimal) -> Decimal:
    # Sum sub-cent amounts before applying one rounding rule to the report total.
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def calculate_monthly_revenue(
    property_id: str, month: int, year: int, tenant_id: str,
    db_session: Optional[AsyncSession] = None,
) -> Decimal:
    result = await calculate_total_revenue(
        property_id, tenant_id, month=month, year=year, db_session=db_session,
    )
    return Decimal(result["total"])


async def calculate_total_revenue(
    property_id: str, tenant_id: str, *, month: Optional[int] = None,
    year: Optional[int] = None, db_session: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    if not tenant_id:
        raise HTTPException(status_code=403, detail="Tenant context required")
    if (month is None) != (year is None):
        raise HTTPException(status_code=422, detail="Month and year must be supplied together")
    if db_session is not None:
        return await _query_revenue(db_session, property_id, tenant_id, month, year)
    await db_pool.initialize()
    async with db_pool.get_session() as session:
        return await _query_revenue(session, property_id, tenant_id, month, year)


async def _query_revenue(
    session: AsyncSession, property_id: str, tenant_id: str,
    month: Optional[int], year: Optional[int],
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"property_id": property_id, "tenant_id": tenant_id}
    property_result = await session.execute(text("""
        SELECT timezone FROM properties
        WHERE id = :property_id AND tenant_id = :tenant_id
    """), params)
    property_row = property_result.fetchone()
    if property_row is None:
        raise HTTPException(status_code=404, detail="Property not found")

    date_filter = ""
    if month is not None and year is not None:
        start, end = month_boundaries(month, year, property_row.timezone)
        params.update(start=start, end=end)
        date_filter = "AND check_in_date >= :start AND check_in_date < :end"

    result = await session.execute(text(f"""
        SELECT currency, SUM(total_amount) AS total_revenue, COUNT(*) AS reservation_count
        FROM reservations
        WHERE property_id = :property_id AND tenant_id = :tenant_id
        {date_filter}
        GROUP BY currency
    """), params)
    rows = result.fetchall()
    if len(rows) > 1:
        raise HTTPException(status_code=422, detail="Cannot sum reservations in different currencies")
    row = rows[0] if rows else None
    if row and not row.currency:
        raise HTTPException(status_code=422, detail="Reservation currency required")
    total = round_revenue(Decimal(str(row.total_revenue))) if row else Decimal("0.00")
    return {
        "property_id": property_id,
        "tenant_id": tenant_id,
        "total": format(total, ".2f"),
        "currency": row.currency if row else "USD",
        "count": row.reservation_count if row else 0,
    }
