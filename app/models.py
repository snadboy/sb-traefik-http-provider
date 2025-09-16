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
    middlewares: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="HTTP middlewares")


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


class ContainerListResponse(BaseModel):
    """Container list response"""
    containers: List[ContainerInfo] = Field(..., description="List of containers")
    count: int = Field(..., description="Total container count")
    host: Optional[str] = Field(None, description="SSH host queried")