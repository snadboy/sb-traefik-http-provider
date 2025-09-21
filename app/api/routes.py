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
    ErrorResponse,
    ContainerListResponse,
    ContainerInfo,
    TraefikHttp,
    ConfigMetadata,
    SystemStatusResponse,
    HostListResponse,
    DebugResponse,
    ExcludedContainer,
    ContainerDiagnostics,
    EnhancedConfigMetadata,
    EnhancedTraefikConfigResponse
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


@router.get("/api/traefik/config", response_model=EnhancedTraefikConfigResponse, response_model_exclude_none=True, responses={
    400: {"model": ErrorResponse},
    500: {"model": ErrorResponse}
})
async def get_traefik_config(
    host: Optional[str] = Query(None, description="Target SSH host to query")
) -> EnhancedTraefikConfigResponse:
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

        return EnhancedTraefikConfigResponse(**config)

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
    Enhanced endpoint to list discovered containers with exclusion info and diagnostics

    Args:
        host: Optional SSH host to query. If not provided, uses default from config

    Returns:
        ContainerListResponse: List of discovered containers with diagnostic information
    """
    logger.info(f"Enhanced container list requested for host: {host or 'default'}")

    try:
        provider = get_provider()

        # Run configuration generation to populate diagnostic data
        await provider.generate_config(host)

        # Get containers after config generation (enables tracking)
        containers = await provider.discover_containers(host)

        target_host = host or provider.config.get('default_host')
        logger.info(f"Returning {len(containers)} containers from {target_host}")

        # Convert to Pydantic models with proper data type handling
        container_models = []
        for c in containers:
            # Handle Labels - convert string to dict if needed
            labels = c.get('Labels', {})
            if isinstance(labels, str):
                # Parse comma-separated labels into dict
                labels_dict = {}
                if labels:
                    for label_pair in labels.split(','):
                        if '=' in label_pair:
                            key, value = label_pair.split('=', 1)
                            labels_dict[key.strip()] = value.strip()
                labels = labels_dict
            elif not isinstance(labels, dict):
                labels = {}

            # Handle Ports - convert string to list if needed
            ports = c.get('Ports', [])
            if isinstance(ports, str):
                # Parse port string into list
                ports_list = []
                if ports:
                    port_entries = ports.split(', ')
                    for port_entry in port_entries:
                        ports_list.append({"port_mapping": port_entry.strip()})
                ports = ports_list
            elif not isinstance(ports, list):
                ports = []

            # Handle Networks - ensure it's a list
            networks = c.get('Networks', {})
            if isinstance(networks, dict):
                networks = list(networks.keys())
            elif isinstance(networks, str):
                networks = [networks] if networks else []
            elif not isinstance(networks, list):
                networks = []

            container_models.append(ContainerInfo(
                ID=c.get('ID', ''),
                Name=c.get('Names', c.get('Name', '')),
                Image=c.get('Image', ''),
                Status=c.get('Status', ''),
                State=c.get('State', 'unknown'),
                Labels=labels,
                Networks=networks,
                Ports=ports,
                Created=c.get('Created'),
                host=target_host
            ))

        # Get excluded containers from diagnostic data
        excluded_container_models = []
        for excluded in provider.excluded_containers:
            excluded_container_models.append(ExcludedContainer(
                id=excluded['id'],
                name=excluded['name'],
                reason=excluded['reason'],
                host=excluded['host'],
                details=excluded.get('details')
            ))

        # Build diagnostics
        total_discovered = len(containers) + len(excluded_container_models)
        containers_with_labels = len([
            c for c in provider.excluded_containers
            if 'snadboy.revp' in c.get('details', '')
        ]) + len(container_models)  # Approximation

        diagnostics = ContainerDiagnostics(
            total_discovered=total_discovered,
            with_labels=containers_with_labels,
            excluded=len(excluded_container_models),
            processing_errors=provider.processing_errors.copy()
        )

        return ContainerListResponse(
            containers=container_models,
            excluded_containers=excluded_container_models,
            diagnostics=diagnostics,
            count=len(container_models),
            host=target_host
        )

    except ValueError as e:
        logger.error(f"Invalid request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to list containers: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/api/status", response_model=SystemStatusResponse)
async def get_system_status() -> SystemStatusResponse:
    """
    Get comprehensive system status including SSH host health and provider configuration

    Returns:
        SystemStatusResponse: Complete system status including SSH hosts and configuration
    """
    logger.info("System status requested")

    try:
        provider = get_provider()

        # Get SSH host statuses
        ssh_hosts = await provider.get_all_ssh_host_status()

        # Determine overall provider status
        reachable_hosts = sum(1 for status in ssh_hosts.values() if status['status'] == 'connected')
        total_hosts = len(ssh_hosts)

        if total_hosts == 0:
            provider_status = "no_hosts_configured"
        elif reachable_hosts == total_hosts:
            provider_status = "healthy"
        elif reachable_hosts > 0:
            provider_status = "partial"
        else:
            provider_status = "unhealthy"

        # Get provider configuration
        enabled_hosts = provider._get_enabled_hosts()
        static_routes_config = provider.config.get('enable_static_routes', False)
        static_routes_count = 0
        if static_routes_config:
            static_routes = provider._load_static_routes()
            static_routes_count = len(static_routes)

        from app.models import ProviderConfiguration, SSHHostStatus
        configuration = ProviderConfiguration(
            enabled_hosts=enabled_hosts,
            label_prefix=provider.config.get('label_prefix', 'snadboy.revp'),
            static_routes_enabled=static_routes_config,
            static_routes_count=static_routes_count,
            default_host=provider.config.get('default_host')
        )

        # Convert SSH host data to SSHHostStatus models
        ssh_host_models = {}
        for hostname, status_data in ssh_hosts.items():
            ssh_host_models[hostname] = SSHHostStatus(**status_data)

        return SystemStatusResponse(
            provider_status=provider_status,
            timestamp=datetime.now(timezone.utc).isoformat(),
            ssh_hosts=ssh_host_models,
            configuration=configuration
        )

    except Exception as e:
        logger.error(f"Failed to get system status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/api/hosts", response_model=HostListResponse)
async def get_ssh_hosts() -> HostListResponse:
    """
    Get SSH host connection statuses

    Returns:
        HostListResponse: SSH host connection statuses
    """
    logger.info("SSH hosts status requested")

    try:
        provider = get_provider()
        ssh_hosts = await provider.get_all_ssh_host_status()

        # Convert to SSHHostStatus models
        from app.models import SSHHostStatus
        ssh_host_models = {}
        for hostname, status_data in ssh_hosts.items():
            ssh_host_models[hostname] = SSHHostStatus(**status_data)

        return HostListResponse(
            hosts=ssh_host_models,
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    except Exception as e:
        logger.error(f"Failed to get SSH hosts status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/api/debug", response_model=DebugResponse)
async def get_debug_info() -> DebugResponse:
    """
    Get detailed debugging information including label parsing, static routes, and SSH diagnostics

    Returns:
        DebugResponse: Comprehensive debugging information
    """
    logger.info("Debug information requested")

    try:
        provider = get_provider()

        # Get label parsing diagnostics
        from app.models import LabelDiagnostics, LabelParsingError
        label_errors = [
            LabelParsingError(
                container=error['container'],
                label=error['label'],
                error=error['error']
            )
            for error in provider.label_parsing_errors
        ]

        # Count containers with snadboy labels
        # This would require running a discovery first, so we'll use cached data
        containers_with_labels = 0
        valid_configurations = 0

        # Try to get recent data from the last configuration generation
        if hasattr(provider, 'excluded_containers'):
            # Count containers that had labels but were excluded for configuration issues
            excluded_with_labels = len([
                c for c in provider.excluded_containers
                if c['reason'] == 'Invalid label configuration'
            ])
            containers_with_labels = excluded_with_labels + len(provider.label_parsing_errors)

        label_diagnostics = LabelDiagnostics(
            containers_with_snadboy_labels=containers_with_labels,
            valid_configurations=valid_configurations,
            invalid_label_format=label_errors
        )

        # Get static route diagnostics
        static_route_diagnostics = provider.get_static_route_diagnostics()
        from app.models import StaticRouteDiagnostics
        static_diagnostics = StaticRouteDiagnostics(**static_route_diagnostics)

        # Get SSH diagnostics
        ssh_diagnostics_data = provider.get_ssh_diagnostics()
        from app.models import SSHDiagnostics
        ssh_diagnostics = SSHDiagnostics(**ssh_diagnostics_data)

        return DebugResponse(
            timestamp=datetime.now(timezone.utc).isoformat(),
            label_parsing=label_diagnostics,
            static_routes=static_diagnostics,
            ssh_diagnostics=ssh_diagnostics
        )

    except Exception as e:
        logger.error(f"Failed to get debug information: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")