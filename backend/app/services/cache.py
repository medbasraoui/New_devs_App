import json
import logging
import redis.asyncio as redis
from typing import Dict, Any, Optional
import os
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Initialize Redis client (typically configured centrally).
redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

async def get_revenue_summary(
    property_id: str, tenant_id: str, *, month: Optional[int] = None, year: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Fetches revenue summary, utilizing caching to improve performance.
    """
    if not tenant_id:
        raise HTTPException(status_code=403, detail="Tenant context required")

    # Versioned, unambiguous keys also exclude legacy, tenant-free cache entries.
    cache_key = "revenue:v2:" + json.dumps([tenant_id, property_id, year, month], separators=(",", ":"))
    
    # Try to get from cache
    cached = await redis_client.get(cache_key)
    if cached:
        result = json.loads(cached)
        if result.get("tenant_id") != tenant_id or result.get("property_id") != property_id:
            logger.error("Revenue cache ownership mismatch")
            raise HTTPException(status_code=503, detail="Revenue cache unavailable")
        return result
    
    # Revenue calculation is delegated to the reservation service.
    from app.services.reservations import calculate_total_revenue
    
    # Calculate revenue
    result = await calculate_total_revenue(property_id, tenant_id, month=month, year=year)
    
    # Cache the result for 5 minutes
    await redis_client.setex(cache_key, 300, json.dumps(result))
    
    return result
