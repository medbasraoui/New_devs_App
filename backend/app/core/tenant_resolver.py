"""
Minimal tenant resolver for authentication.
"""
from typing import Optional
import logging
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class TenantResolver:
    """Minimal tenant resolver that extracts tenant_id from JWT claims."""

    @staticmethod
    def resolve_tenant_from_token(token_payload: dict) -> Optional[str]:
        """
        Extract tenant_id from JWT token payload.

        Args:
            token_payload: Decoded JWT payload

        Returns:
            Tenant ID if found, None otherwise
        """
        # Only use server-controlled claims from an already verified token.
        if 'app_metadata' in token_payload:
            tenant_id = token_payload['app_metadata'].get('tenant_id')
            if tenant_id:
                return tenant_id

        # Try root level
        tenant_id = token_payload.get('tenant_id')
        if tenant_id:
            return tenant_id

        logger.warning("No tenant_id found in token payload")
        return None

    @staticmethod
    def resolve_tenant_from_user(user_data: dict) -> Optional[str]:
        """
        Extract tenant_id from user data.

        Args:
            user_data: User data dictionary

        Returns:
            Tenant ID if found, None otherwise
        """
        # Check various possible locations
        if user_data.get('tenant_id'):
            return user_data['tenant_id']

        if 'app_metadata' in user_data:
            tenant_id = user_data['app_metadata'].get('tenant_id')
            if tenant_id:
                return tenant_id

        return None

    @staticmethod
    async def resolve_tenant_id(user_id: str, user_email: str, token: Optional[str] = None) -> str:
        """
        Resolve tenant ID for a user.
        
        Args:
            user_id: User ID
            user_email: User email
            
        Returns:
            Tenant ID
        """
        from app.database import supabase

        response = supabase.service.table("user_tenants").select("tenant_id").eq(
            "user_id", user_id
        ).eq("is_active", True).execute()
        tenant_ids = {row["tenant_id"] for row in response.data if row.get("tenant_id")}
        if len(tenant_ids) == 1:
            return tenant_ids.pop()
        logger.warning("Missing or ambiguous tenant membership for user %s", user_id)
        raise HTTPException(status_code=403, detail="Tenant context required")

    @staticmethod
    async def update_user_tenant_metadata(user_id: str, tenant_id: str) -> None:
        """
        Update user metadata with tenant_id.
        
        Args:
            user_id: User ID
            tenant_id: Tenant ID
        """
        # No-op in this resolver implementation.
        pass
