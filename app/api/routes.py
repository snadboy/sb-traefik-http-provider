"""
API routes for Traefik HTTP Provider
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from app.core import TraefikProvider
from app.models import (
    HealthResponse,
    TraefikConfigResponse,
    ErrorResponse,
    ContainerListResponse,
    ContainerInfo,
    TraefikHttp,
    ConfigMetadata
)

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')

# Create API router
router = APIRouter()

# Global provider instance
provider: Optional[TraefikProvider] = None


def get_provider() -> TraefikProvider:
    """Get or create provider instance"""
    global provider
    if provider is None:
        provider = TraefikProvider()
    return provider


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint"""
    logger.debug("Health check requested")
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc).isoformat(),
        log_level=logger.level
    )


@router.get("/api/traefik/config", response_model=TraefikConfigResponse, responses={
    400: {"model": ErrorResponse},
    500: {"model": ErrorResponse}
})
async def get_traefik_config(
    host: Optional[str] = Query(None, description="Target SSH host to query")
) -> TraefikConfigResponse:
    """
    Main endpoint for Traefik HTTP provider

    Args:
        host: Optional SSH host to query. If not provided, uses default from config

    Returns:
        TraefikConfigResponse: Complete Traefik configuration
    """
    provider = get_provider()
    target_host = host or provider.config.get('default_host', 'unknown')

    logger.info(f"Configuration request received for host: {host or 'default'} -> using: {target_host}")
    logger.debug("About to call provider.generate_config")
    audit_logger.info(f"Config API called - host: {host}")

    try:
        # Native async call - no event loop management needed!
        config = await provider.generate_config(host)

        # Log generated configuration
        logger.debug(f"Generated routers: {list(config['http']['routers'].keys())}")
        logger.debug(f"Generated services: {list(config['http']['services'].keys())}")

        service_count = len(config['http']['services'])
        logger.info(f"Successfully generated config with {service_count} services for host: {target_host}")
        audit_logger.info(f"Config generated successfully - {service_count} services")

        return TraefikConfigResponse(**config)

    except ValueError as e:
        logger.error(f"Invalid request: {e}")
        audit_logger.error(f"Config generation failed - invalid request: {e}")
        raise HTTPException(
            status_code=400,
            detail={
                "error": str(e),
                "http": {"routers": {}, "services": {}, "middlewares": {}}
            }
        )
    except Exception as e:
        logger.error(f"Failed to generate config: {e}", exc_info=True)
        audit_logger.error(f"Config generation failed with exception: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Internal server error",
                "http": {"routers": {}, "services": {}, "middlewares": {}}
            }
        )


@router.get("/api/containers", response_model=ContainerListResponse)
async def list_containers(
    host: Optional[str] = Query(None, description="Target SSH host to query")
) -> ContainerListResponse:
    """
    Debug endpoint to list discovered containers

    Args:
        host: Optional SSH host to query. If not provided, uses default from config

    Returns:
        ContainerListResponse: List of discovered containers
    """
    logger.info(f"Container list requested for host: {host or 'default'}")

    try:
        provider = get_provider()

        # Native async call
        containers = await provider.discover_containers(host)

        target_host = host or provider.config.get('default_host')
        logger.info(f"Returning {len(containers)} containers from {target_host}")

        # Convert to Pydantic models
        container_models = [
            ContainerInfo(
                ID=c.get('ID', ''),
                Name=c.get('Names', c.get('Name', '')),
                Image=c.get('Image', ''),
                Status=c.get('Status', ''),
                State=c.get('State', 'unknown'),
                Labels=c.get('Labels', {}),
                Networks=list(c.get('Networks', {}).keys()) if isinstance(c.get('Networks'), dict) else [],
                Ports=c.get('Ports', []),
                Created=c.get('Created'),
                host=target_host
            )
            for c in containers
        ]

        return ContainerListResponse(
            containers=container_models,
            count=len(container_models),
            host=target_host
        )

    except ValueError as e:
        logger.error(f"Invalid request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to list containers: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")