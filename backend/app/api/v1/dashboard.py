import logging
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from typing import Dict, Any, Annotated, Optional
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from app.services.cache import get_revenue_summary
from app.services.reservations import round_revenue
from app.core.auth import authenticate_request as get_current_user
from app.models.auth import AuthenticatedUser

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/dashboard/summary")
async def get_dashboard_summary(
    property_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    month: Annotated[Optional[int], Query(ge=1, le=12)] = None,
    year: Annotated[Optional[int], Query(ge=1, le=9998)] = None,
    response: Response = None,
) -> Dict[str, Any]:
    
    tenant_id = current_user.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=403, detail="Tenant context required")
    if (month is None) != (year is None):
        raise HTTPException(status_code=422, detail="Month and year must be supplied together")
    
    try:
        revenue_data = await get_revenue_summary(property_id, tenant_id, month=month, year=year)
    except (SQLAlchemyError, RedisError, OSError) as error:
        logger.exception("Revenue summary unavailable")
        raise HTTPException(status_code=503, detail="Revenue summary unavailable") from error
    
    total = round_revenue(Decimal(revenue_data["total"]))
    if response is not None:
        response.headers["Cache-Control"] = "private, no-store"
    
    return {
        "property_id": revenue_data['property_id'],
        "total_revenue": float(total),
        "total_revenue_exact": format(total, ".2f"),
        "currency": revenue_data['currency'],
        "reservations_count": revenue_data['count']
    }
