"""
Pydantic models for FastAPI request/response validation
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response model"""
    status: str = Field(..., description="Health status")
    timestamp: str = Field(..., description="ISO format timestamp")
    log_level: int = Field(..., description="Current log level")


class TraefikMiddleware(BaseModel):
    """Traefik middleware configuration"""
    pass


class TraefikService(BaseModel):
    """Traefik service configuration"""
    loadBalancer: Dict[str, Any] = Field(..., description="Load balancer configuration")


class TraefikRouter(BaseModel):
    """Traefik router configuration"""
    rule: str = Field(..., description="Router rule")
    service: str = Field(..., description="Service name")
    entryPoints: List[str] = Field(default_factory=list, description="Entry points")
    middlewares: Optional[List[str]] = Field(None, description="Middleware names")
    tls: Optional[Dict[str, Any]] = Field(None, description="TLS configuration")
    priority: Optional[int] = Field(None, description="Router priority")


class TraefikHttp(BaseModel):
    """Traefik HTTP configuration section"""
    routers: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="HTTP routers")
    services: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="HTTP services")
    middlewares: Optional[Dict[str, Dict[str, Any]]] = Field(None, description="HTTP middlewares")

    class Config:
        exclude_none = True


class ConfigMetadata(BaseModel):
    """Metadata about the generated configuration"""
    generated_at: str = Field(..., description="ISO format timestamp when config was generated")
    container_count: int = Field(..., description="Total containers discovered")
    enabled_services: int = Field(..., description="Services with enabled labels")
    hosts_queried: List[str] = Field(default_factory=list, description="SSH hosts that were queried")


class TraefikConfigResponse(BaseModel):
    """Complete Traefik configuration response"""
    http: TraefikHttp = Field(..., description="HTTP configuration")
    metadata: Optional[ConfigMetadata] = Field(None, description="Configuration metadata", alias="_metadata")

    class Config:
        populate_by_name = True


class ErrorResponse(BaseModel):
    """Error response model"""
    error: str = Field(..., description="Error message")
    http: Optional[TraefikHttp] = Field(None, description="Empty HTTP configuration for compatibility")


class ContainerNetwork(BaseModel):
    """Container network information"""
    name: str = Field(..., description="Network name")
    ip_address: Optional[str] = Field(None, description="Container IP in network")
    network_id: Optional[str] = Field(None, description="Network ID")


class ContainerLabel(BaseModel):
    """Container label"""
    key: str = Field(..., description="Label key")
    value: str = Field(..., description="Label value")


class ContainerInfo(BaseModel):
    """Container information model"""
    id: str = Field(..., description="Container ID", alias="ID")
    name: str = Field(..., description="Container name", alias="Name")
    image: str = Field(..., description="Container image", alias="Image")
    status: str = Field(..., description="Container status", alias="Status")
    state: str = Field(..., description="Container state", alias="State")
    labels: Dict[str, str] = Field(default_factory=dict, description="Container labels", alias="Labels")
    networks: List[str] = Field(default_factory=list, description="Network names", alias="Networks")
    ports: Optional[List[Dict[str, Any]]] = Field(None, description="Port mappings", alias="Ports")
    created: Optional[str] = Field(None, description="Container creation time", alias="Created")
    host: Optional[str] = Field(None, description="SSH host where container is running")

    class Config:
        populate_by_name = True


class ExcludedContainer(BaseModel):
    """Information about excluded containers"""
    id: str = Field(..., description="Container ID")
    name: str = Field(..., description="Container name")
    image: str = Field(..., description="Container image")
    status: str = Field(..., description="Container status")
    state: str = Field(..., description="Container state")
    created: Optional[str] = Field(None, description="Container creation time")
    reason: str = Field(..., description="Reason for exclusion")
    host: str = Field(..., description="SSH host where container is running")
    details: Optional[str] = Field(None, description="Additional details about exclusion")


class ContainerDiagnostics(BaseModel):
    """Container discovery diagnostics"""
    total_discovered: int = Field(..., description="Total containers found")
    with_labels: int = Field(..., description="Containers with snadboy.revp labels")
    excluded: int = Field(..., description="Containers excluded from routing")
    processing_errors: List[str] = Field(default_factory=list, description="Processing errors encountered")


class ContainerListResponse(BaseModel):
    """Enhanced container list response with diagnostics"""
    containers: List[ContainerInfo] = Field(..., description="List of containers")
    excluded_containers: List[ExcludedContainer] = Field(default_factory=list, description="Excluded containers")
    diagnostics: ContainerDiagnostics = Field(..., description="Discovery diagnostics")
    count: int = Field(..., description="Total container count")
    host: Optional[str] = Field(None, description="SSH host queried")


class SSHHostStatus(BaseModel):
    """SSH host connection status"""
    hostname: str = Field(..., description="SSH hostname")
    status: str = Field(..., description="Connection status: connected, unreachable, error")
    last_successful_connection: Optional[str] = Field(None, description="ISO timestamp of last successful connection")
    last_attempt: Optional[str] = Field(None, description="ISO timestamp of last connection attempt")
    last_error: Optional[str] = Field(None, description="Last error message")
    error_count: int = Field(default=0, description="Consecutive error count")
    connection_time_ms: Optional[int] = Field(None, description="Last connection time in milliseconds")
    docker_version: Optional[str] = Field(None, description="Docker version on host")
    containers_total: Optional[int] = Field(None, description="Total containers on host")
    containers_running: Optional[int] = Field(None, description="Running containers on host")


class ProviderConfiguration(BaseModel):
    """Provider configuration summary"""
    enabled_hosts: List[str] = Field(default_factory=list, description="List of enabled SSH hosts")
    label_prefix: str = Field(default="snadboy.revp", description="Label prefix for container discovery")
    static_routes_enabled: bool = Field(default=False, description="Whether static routes are enabled")
    static_routes_count: int = Field(default=0, description="Number of static routes configured")
    default_host: Optional[str] = Field(None, description="Default SSH host")


class SystemStatusResponse(BaseModel):
    """Comprehensive system status response"""
    provider_status: str = Field(..., description="Overall provider status")
    timestamp: str = Field(..., description="Status check timestamp")
    ssh_hosts: Dict[str, SSHHostStatus] = Field(default_factory=dict, description="SSH host statuses")
    configuration: ProviderConfiguration = Field(..., description="Provider configuration")


class HostListResponse(BaseModel):
    """SSH hosts status response"""
    hosts: Dict[str, SSHHostStatus] = Field(..., description="SSH host statuses")
    timestamp: str = Field(..., description="Status check timestamp")


class LabelParsingError(BaseModel):
    """Label parsing error details"""
    container: str = Field(..., description="Container name")
    label: str = Field(..., description="Problematic label")
    error: str = Field(..., description="Error description")


class LabelDiagnostics(BaseModel):
    """Label parsing diagnostics"""
    containers_with_snadboy_labels: int = Field(..., description="Containers with snadboy.revp labels")
    valid_configurations: int = Field(..., description="Containers with valid label configurations")
    invalid_label_format: List[LabelParsingError] = Field(default_factory=list, description="Label parsing errors")


class StaticRouteDiagnostics(BaseModel):
    """Static route diagnostics"""
    loaded: int = Field(..., description="Successfully loaded static routes")
    errors: List[str] = Field(default_factory=list, description="Static route errors")


class SSHDiagnostics(BaseModel):
    """SSH connection diagnostics"""
    key_files: List[str] = Field(default_factory=list, description="SSH key files found")
    connection_timeouts: int = Field(default=0, description="Number of connection timeouts")
    permission_errors: int = Field(default=0, description="Number of permission errors")
    hosts_configured: int = Field(default=0, description="Total hosts configured")
    hosts_reachable: int = Field(default=0, description="Hosts currently reachable")


class DebugResponse(BaseModel):
    """Detailed debugging information"""
    timestamp: str = Field(..., description="Debug info generation timestamp")
    label_parsing: LabelDiagnostics = Field(..., description="Label parsing diagnostics")
    static_routes: StaticRouteDiagnostics = Field(..., description="Static route diagnostics")
    ssh_diagnostics: SSHDiagnostics = Field(..., description="SSH connection diagnostics")


class EnhancedConfigMetadata(ConfigMetadata):
    """Enhanced configuration metadata with diagnostic info"""
    processing_time_ms: Optional[int] = Field(None, description="Configuration generation time in milliseconds")
    hosts_successful: List[str] = Field(default_factory=list, description="Successfully queried hosts")
    hosts_failed: List[str] = Field(default_factory=list, description="Failed hosts")
    excluded_containers: int = Field(default=0, description="Number of excluded containers")
    static_routes: int = Field(default=0, description="Number of static routes")


class EnhancedTraefikConfigResponse(BaseModel):
    """Enhanced Traefik configuration response with diagnostics"""
    http: TraefikHttp = Field(..., description="HTTP configuration")
    metadata: Optional[EnhancedConfigMetadata] = Field(None, description="Enhanced configuration metadata", alias="_metadata")

    class Config:
        populate_by_name = True