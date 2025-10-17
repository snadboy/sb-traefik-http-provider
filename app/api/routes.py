"""
API routes for Traefik HTTP Provider
"""

import logging
import asyncio
import subprocess
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from fastapi import APIRouter, Query, HTTPException
from app.core import TraefikProvider
from app.utils.ssh_setup import scan_and_add_ssh_keys
from app.utils.dns_health import perform_dns_health_check
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
    EnhancedTraefikConfigResponse,
    EnvironmentDiagnosticsResponse,
    ContainerInfoModel,
    DNSConfigModel,
    NetworkConfigModel,
    TailscaleStatusModel,
    SSHHostStatus,
    CacheStatusModel,
    EventListenerStatus
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


@router.get("/api/health/dns")
async def dns_health_check() -> Dict[str, Any]:
    """
    DNS health check endpoint

    Performs DNS resolution checks against configured nameservers (Tailscale, LAN)
    and optionally checks HTTP connectivity to Technitium admin interface.

    Configuration via environment variables:
    - DNS_CHECK_NAME: Domain to test (default: sonarr.isnadboy.com)
    - DNS_CHECK_NS_TS: Tailscale nameserver (default: 100.65.231.21)
    - DNS_CHECK_NS_LAN: LAN nameserver (optional)
    - DNS_CHECK_ADMIN_URL: Admin URL to check (optional)

    Returns:
        DNS health check results with detailed check status
    """
    logger.info("DNS health check requested via API")
    result = perform_dns_health_check()

    # Add timestamp
    result['timestamp'] = datetime.now(timezone.utc).isoformat()

    return result


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
    target_host = host or 'all'

    logger.info(f"Configuration request received for host: {host or 'all hosts'}")
    logger.debug("About to call provider.generate_config")
    audit_logger.info(f"Config API called - host: {host}")

    try:
        # Native async call - no event loop management needed!
        config = await provider.generate_config(host)

        # Log generated configuration
        services_dict = config['http']['services']
        routers_dict = config['http']['routers']
        service_count = len(services_dict)
        logger.debug(f"Generated routers: {list(routers_dict.keys())}")

        # Build a map of service -> domain from routers
        service_to_domain = {}
        for router_name, router_config in routers_dict.items():
            service_name = router_config.get('service')
            rule = router_config.get('rule', '')
            # Extract domain from rule like "Host(`example.com`)"
            if service_name and 'Host(' in rule:
                domain = rule.split('Host(`')[1].split('`)')[0] if '`)' in rule else 'unknown'
                # Prefer HTTPS router for display
                if 'https' in router_name or service_name not in service_to_domain:
                    entrypoints = router_config.get('entryPoints', [])
                    protocol = 'https' if 'websecure' in entrypoints else 'http'
                    service_to_domain[service_name] = f"{protocol}://{domain}"

        # Log services with URLs and domains in numbered list format
        logger.info(f"API request: Found {service_count} service(s) for host: {target_host}")
        for idx, (service_name, service_config) in enumerate(services_dict.items(), 1):
            backend_url = service_config.get('loadBalancer', {}).get('servers', [{}])[0].get('url', 'unknown')
            domain = service_to_domain.get(service_name, 'no domain')
            logger.info(f"  [{idx}] {service_name}: {domain} -> {backend_url}")

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

        # Run configuration generation to populate diagnostic data and store processed containers
        await provider.generate_config(host)

        # Use the processed containers from configuration generation
        # This ensures consistency between included/excluded tracking
        processed_containers = provider.last_processed_containers

        # Filter out containers that were excluded (to avoid duplicates)
        excluded_ids = {excluded['id'] for excluded in provider.excluded_containers}

        # Convert processed containers to the format expected by container models
        containers_all = []
        for container_data in processed_containers:
            container = container_data.get('container', {})
            details = container_data.get('details', {})
            source_host = container_data.get('source_host', 'unknown')

            # Skip containers that were tracked as excluded
            container_id = container.get('ID', '')
            if container_id in excluded_ids:
                continue

            # Add source host info and convert to expected format
            container_info = container.copy()
            container_info['_source_host'] = source_host

            # Extract status from container data (not from details)
            if 'Status' not in container_info and details:
                # Try to get status from details if not in container
                state_info = details.get('State', {})
                if isinstance(state_info, dict):
                    container_info['Status'] = state_info.get('Status', 'unknown')
                    container_info['State'] = 'running' if state_info.get('Running') else 'stopped'

            containers_all.append(container_info)

        target_hosts = [host] if host else provider._get_enabled_hosts()
        logger.info(f"Returning {len(containers_all)} included containers from {target_hosts}")

        # Convert to Pydantic models with proper data type handling
        container_models = []
        for c in containers_all:
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
                host=c.get('_source_host', target_hosts[0] if len(target_hosts) == 1 else 'unknown')
            ))

        # Get excluded containers from diagnostic data
        excluded_container_models = []
        for excluded in provider.excluded_containers:
            excluded_container_models.append(ExcludedContainer(
                id=excluded['id'],
                name=excluded['name'],
                image=excluded.get('image', ''),
                status=excluded.get('status', ''),
                state=excluded.get('state', 'unknown'),
                created=excluded.get('created'),
                reason=excluded['reason'],
                host=excluded['host'],
                details=excluded.get('details')
            ))

        # Build diagnostics
        total_discovered = len(containers_all) + len(excluded_container_models)
        containers_with_labels = len([
            c for c in provider.excluded_containers
            if 'snadboy.revp' in (c.get('details') or '')
        ]) + len(container_models)  # Approximation

        diagnostics = ContainerDiagnostics(
            total_discovered=total_discovered,
            with_labels=containers_with_labels,
            excluded=len(excluded_container_models),
            processing_errors=provider.processing_errors.copy()
        )

        # Data consistency validation - ensure no duplicates between included and excluded
        included_ids = {c.id for c in container_models}
        excluded_ids_check = {c.id for c in excluded_container_models}
        duplicate_ids = included_ids.intersection(excluded_ids_check)

        if duplicate_ids:
            logger.error(f"CONSISTENCY ERROR: Found {len(duplicate_ids)} containers in both included and excluded lists: {duplicate_ids}")
            # Remove duplicates from included list to prevent API inconsistency
            container_models = [c for c in container_models if c.id not in duplicate_ids]
            logger.warning(f"Removed {len(duplicate_ids)} duplicate containers from included list")

        return ContainerListResponse(
            containers=container_models,
            excluded_containers=excluded_container_models,
            diagnostics=diagnostics,
            count=len(container_models),
            host=host or "all_hosts"
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
        static_routes = provider._load_static_routes()
        static_routes_count = len(static_routes)

        from app.models import ProviderConfiguration, SSHHostStatus
        configuration = ProviderConfiguration(
            enabled_hosts=enabled_hosts,
            label_prefix='snadboy.revp',
            static_routes_enabled=True,
            static_routes_count=static_routes_count,
            default_host=None
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

        # Run a configuration generation to populate diagnostic data
        # This ensures we have fresh diagnostic information
        config = await provider.generate_config()

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

        # After running generate_config, we can get accurate counts
        # Count successfully configured services (excluding static routes)
        all_services = len(config['http']['services'])
        static_routes_count = len(provider._load_static_routes())
        valid_configurations = all_services - static_routes_count

        # Count containers that had labels but were excluded for configuration issues
        excluded_with_labels = len([
            c for c in provider.excluded_containers
            if c['reason'] == 'Invalid label configuration'
        ])

        # Total containers with snadboy labels = valid configs + excluded with invalid labels
        containers_with_labels = valid_configurations + excluded_with_labels

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


@router.get("/api/ssh/test/{host}")
async def test_ssh_connectivity(host: str) -> Dict[str, Any]:
    """Test SSH connectivity to a specific host"""
    logger.info(f"Testing SSH connectivity to host: {host}")

    try:
        provider = get_provider()

        # Check if host is in configuration
        enabled_hosts = provider._get_enabled_hosts()
        if host not in enabled_hosts:
            return {
                "host": host,
                "status": "error",
                "message": f"Host '{host}' is not in enabled hosts list",
                "enabled_hosts": enabled_hosts
            }

        # Get hostname from configuration
        hostname = provider._get_ssh_hostname(host)

        # Test DNS resolution
        dns_test = subprocess.run(
            ["nslookup", hostname],
            capture_output=True,
            text=True,
            timeout=10
        )
        dns_resolved = dns_test.returncode == 0

        # Test SSH port connectivity
        port_test = subprocess.run(
            ["timeout", "5", "bash", "-c", f"echo > /dev/tcp/{hostname}/22"],
            capture_output=True,
            text=True
        )
        port_open = port_test.returncode == 0

        # Check known_hosts
        known_hosts_path = "/root/.ssh/known_hosts"
        host_in_known_hosts = False
        if os.path.exists(known_hosts_path):
            with open(known_hosts_path, 'r') as f:
                known_hosts_content = f.read()
                # Check for hashed entries (they start with |1|)
                host_in_known_hosts = f"|1|" in known_hosts_content or hostname in known_hosts_content

        # Try actual SSH connection
        ssh_test_result = None
        ssh_test_error = None
        try:
            # Simple SSH command to test connectivity
            ssh_result = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
                 f"revp@{hostname}", "echo", "SSH_TEST_SUCCESS"],
                capture_output=True,
                text=True,
                timeout=15
            )
            ssh_test_result = ssh_result.returncode == 0
            ssh_test_error = ssh_result.stderr if not ssh_test_result else None
        except Exception as e:
            ssh_test_result = False
            ssh_test_error = str(e)

        # Try container discovery
        container_count = 0
        discovery_error = None
        try:
            containers = await provider.discover_containers(host)
            container_count = len(containers)
        except Exception as e:
            discovery_error = str(e)

        return {
            "host": host,
            "hostname": hostname,
            "status": "success" if ssh_test_result else "failed",
            "diagnostics": {
                "dns_resolved": dns_resolved,
                "port_22_open": port_open,
                "host_in_known_hosts": host_in_known_hosts,
                "ssh_connection_test": ssh_test_result,
                "container_discovery": {
                    "success": discovery_error is None,
                    "container_count": container_count,
                    "error": discovery_error
                }
            },
            "errors": {
                "ssh_error": ssh_test_error,
                "discovery_error": discovery_error
            },
            "recommendations": _get_ssh_recommendations(
                dns_resolved, port_open, host_in_known_hosts, ssh_test_result, ssh_test_error
            )
        }

    except Exception as e:
        logger.error(f"Failed to test SSH connectivity: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/ssh/scan-keys/{host}")
async def scan_ssh_keys(host: str) -> Dict[str, Any]:
    """Manually scan and add SSH keys for a host"""
    logger.info(f"Manually scanning SSH keys for host: {host}")

    try:
        provider = get_provider()
        hostname = provider._get_ssh_hostname(host)

        # Use the shared SSH setup utility function
        result = scan_and_add_ssh_keys(hostname, timeout=15, retries=3)

        # Add the original host parameter to the result
        result["host"] = host
        result["hostname"] = hostname

        return result

    except Exception as e:
        logger.error(f"Failed to scan SSH keys: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/ssh/known-hosts")
async def get_known_hosts() -> Dict[str, Any]:
    """Get current SSH known_hosts information"""
    try:
        known_hosts_path = "/root/.ssh/known_hosts"

        if not os.path.exists(known_hosts_path):
            return {
                "status": "empty",
                "message": "No known_hosts file exists",
                "total_entries": 0
            }

        with open(known_hosts_path, 'r') as f:
            lines = f.readlines()

        # Count hashed vs unhashed entries
        hashed_count = sum(1 for line in lines if line.startswith('|1|'))
        unhashed_count = len(lines) - hashed_count

        return {
            "status": "ok",
            "total_entries": len(lines),
            "hashed_entries": hashed_count,
            "unhashed_entries": unhashed_count,
            "file_path": known_hosts_path,
            "file_size_bytes": os.path.getsize(known_hosts_path)
        }

    except Exception as e:
        logger.error(f"Failed to get known_hosts info: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _get_ssh_recommendations(dns_resolved: bool, port_open: bool,
                            host_in_known_hosts: bool, ssh_test: bool,
                            ssh_error: str) -> list:
    """Generate recommendations based on SSH test results"""
    recommendations = []

    if not dns_resolved:
        recommendations.append("DNS resolution failed - check hostname and network connectivity")
        recommendations.append("Ensure Tailscale MagicDNS is working (100.100.100.100)")

    if dns_resolved and not port_open:
        recommendations.append("Port 22 is not accessible - check if SSH is enabled on target host")
        recommendations.append("Run 'tailscale up --ssh' on the target host")

    if port_open and not host_in_known_hosts:
        recommendations.append("Host key not in known_hosts - use /api/ssh/scan-keys/{host} to add it")

    if ssh_error and "Host key verification failed" in ssh_error:
        recommendations.append("Host key verification failed - the host key has changed or is not trusted")
        recommendations.append("Use /api/ssh/scan-keys/{host} to update the host key")

    if ssh_error and "Permission denied" in ssh_error:
        recommendations.append("Authentication failed - check Tailscale SSH is enabled")
        recommendations.append("Ensure the user 'revp' exists on the target host")

    if not recommendations and ssh_test:
        recommendations.append("SSH connectivity is working properly")

    return recommendations


@router.get("/api/diagnostics/environment", response_model=EnvironmentDiagnosticsResponse)
async def get_environment_diagnostics() -> EnvironmentDiagnosticsResponse:
    """
    Get comprehensive environment diagnostics including:
    - Container image and version info
    - DNS configuration and search order
    - Network configuration
    - Tailscale availability and hostname resolution
    - SSH connectivity to remote hosts
    - Cache status
    - Event listener status
    """
    try:
        provider = get_provider()

        # Container info
        container_info = _get_container_info()

        # DNS configuration
        dns_config = _get_dns_config()

        # Network configuration
        network_config = _get_network_config()

        # Tailscale status
        tailscale_status = _get_tailscale_status(provider)

        # SSH connectivity
        ssh_connectivity = await _get_ssh_connectivity(provider)

        # Cache status
        cache_status = provider.get_cache_info()

        # Event listener status
        event_listeners = provider.get_event_listener_status()

        return EnvironmentDiagnosticsResponse(
            container_info=ContainerInfoModel(**container_info),
            dns_config=DNSConfigModel(**dns_config),
            network_config=NetworkConfigModel(**network_config),
            tailscale_status=TailscaleStatusModel(**tailscale_status),
            ssh_connectivity={k: SSHHostStatus(**v) for k, v in ssh_connectivity.items()},
            cache_status=CacheStatusModel(**cache_status),
            event_listeners={k: EventListenerStatus(**v) for k, v in event_listeners.items()}
        )

    except Exception as e:
        logger.error(f"Failed to gather environment diagnostics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _get_container_info() -> Dict[str, Any]:
    """Get information about the running container"""
    try:
        # Try to read from Docker environment
        hostname = subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip()

        # Try to get image info from environment or Docker
        image = os.getenv("HOSTNAME", "unknown")

        return {
            "image": image,
            "image_digest": None,  # Would need Docker API access
            "created": None,
            "started": None
        }
    except Exception as e:
        logger.warning(f"Could not get container info: {e}")
        return {
            "image": "unknown",
            "image_digest": None,
            "created": None,
            "started": None
        }


def _get_dns_config() -> Dict[str, Any]:
    """Get DNS configuration"""
    try:
        with open("/etc/resolv.conf", "r") as f:
            resolv_content = f.read()

        nameservers = []
        search_domains = []
        ext_servers = []

        for line in resolv_content.split("\n"):
            line = line.strip()
            if line.startswith("nameserver"):
                nameservers.append(line.split()[1])
            elif line.startswith("search"):
                search_domains = line.split()[1:]
            elif line.startswith("# ExtServers:"):
                # Extract ExtServers from Docker comment
                ext_part = line.split("# ExtServers:")[1].strip()
                if ext_part.startswith("[") and ext_part.endswith("]"):
                    ext_servers_raw = ext_part[1:-1].split(",")
                    for srv in ext_servers_raw:
                        srv = srv.strip()
                        if srv.startswith("host(") and srv.endswith(")"):
                            ext_servers.append(srv[5:-1])
                        else:
                            ext_servers.append(srv)

        return {
            "nameservers": nameservers,
            "search_domains": search_domains,
            "ext_servers": ext_servers,
            "resolv_conf": resolv_content
        }
    except Exception as e:
        logger.warning(f"Could not read DNS config: {e}")
        return {
            "nameservers": [],
            "search_domains": [],
            "ext_servers": [],
            "resolv_conf": None
        }


def _get_network_config() -> Dict[str, Any]:
    """Get network configuration"""
    try:
        # Get hostname
        hostname_result = subprocess.run(["hostname"], capture_output=True, text=True)
        hostname = hostname_result.stdout.strip()

        # Try to get IP addresses
        ip_result = subprocess.run(["hostname", "-I"], capture_output=True, text=True)
        ips = ip_result.stdout.strip().split()

        return {
            "networks": ["traefik"],  # Known from compose
            "ip_addresses": {"traefik": ips[0] if ips else "unknown"},
            "gateway": None  # Would need route command
        }
    except Exception as e:
        logger.warning(f"Could not get network config: {e}")
        return {
            "networks": [],
            "ip_addresses": {},
            "gateway": None
        }


def _get_tailscale_status(provider: TraefikProvider) -> Dict[str, Any]:
    """Get Tailscale status"""
    try:
        enabled_hosts = provider._get_enabled_hosts()
        can_resolve = {}

        for host in enabled_hosts:
            try:
                result = subprocess.run(
                    ["getent", "hosts", host],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0:
                    ip = result.stdout.strip().split()[0]
                    can_resolve[host] = ip
            except Exception:
                pass

        # Count SSH keys
        ssh_keys_scanned = 0
        try:
            if os.path.exists("/root/.ssh/known_hosts"):
                with open("/root/.ssh/known_hosts", "r") as f:
                    ssh_keys_scanned = len(f.readlines())
        except Exception:
            pass

        return {
            "available": len(can_resolve) > 0,
            "can_resolve": can_resolve,
            "ssh_keys_scanned": ssh_keys_scanned
        }
    except Exception as e:
        logger.warning(f"Could not get Tailscale status: {e}")
        return {
            "available": False,
            "can_resolve": {},
            "ssh_keys_scanned": 0
        }


async def _get_ssh_connectivity(provider: TraefikProvider) -> Dict[str, Dict[str, Any]]:
    """Get SSH connectivity status for all hosts"""
    enabled_hosts = provider._get_enabled_hosts()
    connectivity = {}

    for host in enabled_hosts:
        try:
            await provider.check_ssh_host_health(host)
            host_status = provider.ssh_host_status.get(host, {})

            connectivity[host] = {
                "reachable": host_status.get("status") == "connected",
                "running_count": host_status.get("running_count", 0),
                "stopped_count": host_status.get("stopped_count", 0),
                "with_labels_count": host_status.get("with_labels_count", 0),
                "running_names": host_status.get("running_names", []),
                "stopped_names": host_status.get("stopped_names", []),
                "with_labels_names": host_status.get("with_labels_names", []),
                "last_check": host_status.get("last_attempt")
            }
        except Exception as e:
            logger.warning(f"Could not check SSH connectivity for {host}: {e}")
            connectivity[host] = {
                "reachable": False,
                "running_count": 0,
                "stopped_count": 0,
                "with_labels_count": 0,
                "running_names": [],
                "stopped_names": [],
                "with_labels_names": [],
                "last_check": None
            }

    return connectivity


# Dashboard API Endpoints

@router.get("/api/services")
async def get_services() -> Dict[str, Any]:
    """Get formatted list of services for dashboard"""
    try:
        provider = get_provider()
        config = await provider.generate_config()

        services = []
        http_services = config.get('http', {}).get('services', {})
        http_routers = config.get('http', {}).get('routers', {})

        # Build service information from routers and services
        for router_name, router_config in http_routers.items():
            service_name = router_config.get('service')
            if not service_name or service_name in [s['name'] for s in services]:
                continue

            service_config = http_services.get(service_name, {})
            servers = service_config.get('loadBalancer', {}).get('servers', [])
            backend_url = servers[0].get('url') if servers else None

            # Get domains from router rule (supports multiple domains with OR operator)
            # e.g., "Host(`app.com`) || Host(`app2.com`)" -> ["app.com", "app2.com"]
            rule = router_config.get('rule', '')
            domains = []
            if 'Host(' in rule:
                import re
                # Extract all Host(`domain`) patterns
                domain_matches = re.findall(r'Host\(`([^`]+)`\)', rule)
                domains = domain_matches if domain_matches else []

            # Determine if HTTPS
            entry_points = router_config.get('entryPoints', [])
            is_https = 'websecure' in entry_points

            # Extract host and container info from backend URL
            host = None
            container = None
            is_static = service_name.startswith('static-')

            if backend_url:
                # Extract host from URL (e.g., http://fabric:3001/ -> fabric)
                match = re.match(r'https?://([^:]+)', backend_url)
                if match:
                    host = match.group(1)
                    if not is_static and host not in ['localhost', '127.0.0.1']:
                        # Extract container name from service name (e.g., uptime-kuma-3001 -> uptime-kuma)
                        container = service_name.rsplit('-', 1)[0] if '-' in service_name else service_name

            # Build public URLs for all domains
            public_urls = []
            for domain in domains:
                url = f"https://{domain}" if is_https else f"http://{domain}"
                public_urls.append({'domain': domain, 'url': url})

            services.append({
                'name': service_name,
                'domains': domains,  # All domains for this service
                'public_urls': public_urls,  # All public URLs
                'public_url': public_urls[0]['url'] if public_urls else None,  # Primary URL for compatibility
                'backend_url': backend_url,
                'host': host,
                'container': container,
                'is_static': is_static
            })

        return {
            'services': sorted(services, key=lambda x: (x['is_static'], x['name'])),
            'total': len(services)
        }

    except Exception as e:
        logger.error(f"Failed to get services: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/containers/grouped")
async def get_containers_grouped() -> Dict[str, Any]:
    """Get containers grouped by host for dashboard"""
    try:
        provider = get_provider()

        # Get all enabled hosts
        enabled_hosts = provider._get_enabled_hosts()

        hosts_data = {}
        for host in enabled_hosts:
            try:
                containers = await provider.discover_containers(host)

                container_list = []
                for container in containers:
                    # Get container details
                    raw_names = container.get('Names', [])
                    if isinstance(raw_names, list):
                        name = raw_names[0].strip('/') if raw_names else 'unknown'
                    elif isinstance(raw_names, str):
                        name = raw_names.strip('/')
                    else:
                        name = 'unknown'

                    # Parse status
                    status_str = container.get('Status', '')
                    status = 'running' if 'Up' in status_str else 'stopped'

                    # Get ports
                    ports_str = container.get('Ports', '')

                    container_list.append({
                        'id': container.get('ID', '')[:12],
                        'name': name,
                        'image': container.get('Image', 'unknown'),
                        'status': status,
                        'ports': ports_str
                    })

                hosts_data[host] = {
                    'containers': container_list,
                    'count': len(container_list)
                }

            except Exception as e:
                logger.error(f"Failed to get containers for {host}: {e}")
                hosts_data[host] = {
                    'containers': [],
                    'count': 0,
                    'error': str(e)
                }

        return {'hosts': hosts_data}

    except Exception as e:
        logger.error(f"Failed to get grouped containers: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/events")
async def get_events(limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    """Get recent container events"""
    try:
        provider = get_provider()

        # Get event history from provider
        events = provider.get_event_history(limit=limit)

        # Get event listener stats
        event_stats = provider.get_event_listener_status()

        return {
            'events': list(reversed(events)),  # Most recent first
            'total': len(events),
            'listeners': event_stats
        }

    except Exception as e:
        logger.error(f"Failed to get events: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))