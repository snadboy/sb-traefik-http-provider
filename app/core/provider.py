"""
Traefik HTTP Provider using snadboy-ssh-docker
"""

import asyncio
import os
import yaml
import logging
import re
import time
import subprocess
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone
from pathlib import Path
from snadboy_ssh_docker import SSHDockerClient

logger = logging.getLogger(__name__)


class SSHDockerClientDebugWrapper:
    """Debug wrapper for SSHDockerClient to log commands"""

    def __init__(self, client):
        self._client = client
        self._original_run = None
        self._patch_subprocess()

    def _patch_subprocess(self):
        """Monkey-patch subprocess to capture SSH commands"""
        original_run = subprocess.run

        def debug_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) > 0 and 'ssh' in cmd[0]:
                logger.debug(f"SSH COMMAND: {' '.join(cmd)}")
            return original_run(cmd, *args, **kwargs)

        subprocess.run = debug_run
        self._original_run = original_run

    def __getattr__(self, name):
        """Forward all other attributes to the wrapped client"""
        attr = getattr(self._client, name)

        # Don't wrap async generators (like docker_events)
        if hasattr(attr, '__name__') and name == 'docker_events':
            logger.debug(f"Passing through async generator: {name}")
            return attr

        if callable(attr):
            async def wrapper(*args, **kwargs):
                logger.debug(f"Calling SSHDockerClient.{name} with args={args}, kwargs={kwargs}")
                try:
                    result = await attr(*args, **kwargs)
                    logger.debug(f"SSHDockerClient.{name} completed successfully")
                    return result
                except Exception as e:
                    logger.error(f"SSHDockerClient.{name} failed: {e}")
                    raise
            return wrapper
        return attr


class TraefikProvider:
    """Manages Docker discovery and Traefik configuration generation"""

    def __init__(self, config_file: str = "config/provider-config.yaml"):
        self.config_file = config_file
        self.config = self._load_config()
        self.ssh_client = None
        self._initialize_client()

        # Diagnostic tracking
        self.ssh_host_status: Dict[str, Dict[str, Any]] = {}
        self.excluded_containers: List[Dict[str, Any]] = []
        self.processing_errors: List[str] = []
        self.label_parsing_errors: List[Dict[str, str]] = []

        # Store processed containers from last configuration generation
        self.last_processed_containers: List[Dict[str, Any]] = []

        # Event-driven caching
        self._config_cache: Optional[Dict[str, Any]] = None
        self._cache_lock = asyncio.Lock()
        self._cache_timestamp: Optional[float] = None
        self._event_listener_tasks: Dict[str, asyncio.Task] = {}
        self._event_stats: Dict[str, int] = {}  # Track events received per host
        self._shutdown_event = asyncio.Event()

        # Debouncing for cache refreshes (batch multiple events together)
        self._pending_refresh: Optional[asyncio.Task] = None
        self._refresh_debounce_seconds = 2.0  # Wait 2 seconds after last event before refreshing

    def _load_config(self) -> Dict[str, Any]:
        """Load provider configuration"""
        if not os.path.exists(self.config_file):
            logger.warning(f"Config file {self.config_file} not found, using defaults")
            return self._default_config()

        with open(self.config_file, 'r') as f:
            config = yaml.safe_load(f)
            logger.info(f"Loaded configuration from {self.config_file}")
            return config

    def _default_config(self) -> Dict[str, Any]:
        """Return default configuration"""
        return {
            'ssh_hosts_file': 'config/ssh-hosts.yaml',
            'default_host': None,
            'enable_tls': False,
            'default_rule_type': 'Host',
            'network_mode': 'bridge',
            'refresh_interval': 30
        }

    def _initialize_client(self):
        """Initialize SSH Docker client with Tailscale authentication"""
        try:
            ssh_hosts_file = self.config.get('ssh_hosts_file', 'config/ssh-hosts.yaml')
            ssh_hosts_path = Path(ssh_hosts_file).resolve()

            if not ssh_hosts_path.exists():
                error_msg = f"SSH hosts configuration file not found: {ssh_hosts_path}"
                logger.error(error_msg)
                raise FileNotFoundError(error_msg)

            # Create the base client
            base_client = SSHDockerClient(config_file=ssh_hosts_path)

            # Wrap it with debug logging if DEBUG level is enabled
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Wrapping SSHDockerClient with debug logging")
                self.ssh_client = SSHDockerClientDebugWrapper(base_client)
            else:
                self.ssh_client = base_client

            logger.info("SSH Docker client initialized successfully with Tailscale authentication")
            logger.info(f"Using hosts configuration: {ssh_hosts_path}")

        except Exception as e:
            logger.error(f"CRITICAL: Failed to initialize SSH client: {e}")
            logger.error("This is a fatal error. The provider cannot function without SSH connectivity.")
            logger.error("Ensure Tailscale is installed and SSH is enabled on all hosts: tailscale up --ssh")
            raise

    def _get_enabled_hosts(self) -> List[str]:
        """Get list of enabled hosts from SSH hosts configuration"""
        try:
            ssh_hosts_file = self.config.get('ssh_hosts_file', 'config/ssh-hosts.yaml')
            if not os.path.exists(ssh_hosts_file):
                logger.warning(f"SSH hosts file {ssh_hosts_file} not found")
                return []

            with open(ssh_hosts_file, 'r') as f:
                ssh_config = yaml.safe_load(f)

            enabled_hosts = []
            hosts = ssh_config.get('hosts', {})
            for host_name, host_config in hosts.items():
                if host_config.get('enabled', True):
                    enabled_hosts.append(host_name)

            logger.debug(f"Found enabled hosts: {enabled_hosts}")
            return enabled_hosts
        except Exception as e:
            logger.error(f"Failed to get enabled hosts: {e}")
            return []

    def _get_ssh_hostname(self, alias: str) -> str:
        """Get the actual hostname for an SSH alias from config"""
        try:
            ssh_hosts_file = self.config.get('ssh_hosts_file', 'config/ssh-hosts.yaml')
            if os.path.exists(ssh_hosts_file):
                with open(ssh_hosts_file, 'r') as f:
                    ssh_config = yaml.safe_load(f)
                    host_config = ssh_config.get('hosts', {}).get(alias, {})
                    hostname = host_config.get('hostname', alias)
                    logger.debug(f"Resolved SSH alias '{alias}' to hostname '{hostname}'")
                    return hostname
        except Exception as e:
            logger.warning(f"Failed to resolve hostname for alias '{alias}': {e}")

        # Fall back to alias if we can't resolve
        return alias

    async def discover_containers(self, host: Optional[str] = None) -> List[Dict[str, Any]]:
        """Discover running containers on specified host"""
        target_host = host or self.config.get('default_host')
        if not target_host:
            raise ValueError("No host specified and no default_host in config")

        try:
            logger.debug(f"Starting container discovery on host: {target_host}")
            containers = await self.ssh_client.list_containers(
                host=target_host,
                filters={"STATUS": "running"}
            )
            logger.info(f"Discovered {len(containers)} running containers on {target_host}")
            return containers
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to discover containers on {target_host}: {error_msg}")

            # Provide more detailed error information for common SSH issues
            if "Host key verification failed" in error_msg:
                logger.error(f"SSH host key verification failed for '{target_host}'")
                logger.error("Possible solutions:")
                logger.error("1. Run: ssh-keyscan -H {target_host} >> ~/.ssh/known_hosts")
                logger.error("2. Check if Tailscale is running and SSH is enabled")
                logger.error("3. Verify the hostname is correct in ssh-hosts.yaml")
            elif "Connection refused" in error_msg:
                logger.error(f"SSH connection refused by '{target_host}'")
                logger.error("Ensure SSH is enabled on the target host")
            elif "No route to host" in error_msg or "Name or service not known" in error_msg:
                logger.error(f"Cannot reach '{target_host}'")
                logger.error("Check network connectivity and hostname resolution")

            return []

    async def inspect_container(self, host: str, container_id: str) -> Dict[str, Any]:
        """Get detailed container information"""
        try:
            return await self.ssh_client.inspect_container(
                host=host,
                container_id=container_id
            )
        except Exception as e:
            logger.error(f"Failed to inspect container {container_id}: {e}")
            return {}

    def _load_static_routes(self) -> List[Dict[str, Any]]:
        """Load static routes from configuration file"""
        static_routes = []

        # Check if static routes are enabled
        if not self.config.get('enable_static_routes', False):
            logger.debug("Static routes disabled in configuration")
            return static_routes

        static_routes_file = self.config.get('static_routes_file', 'config/static-routes.yaml')
        if not os.path.exists(static_routes_file):
            logger.warning(f"Static routes file {static_routes_file} not found")
            return static_routes

        try:
            with open(static_routes_file, 'r') as f:
                routes_config = yaml.safe_load(f)

            raw_routes = routes_config.get('static_routes', [])
            logger.info(f"Loading {len(raw_routes)} static routes from {static_routes_file}")

            for route in raw_routes:
                domain = route.get('domain')
                target = route.get('target')

                if not domain or not target:
                    logger.warning(f"Skipping invalid static route: {route}")
                    continue

                # Apply defaults similar to container routes
                https_enabled = route.get('https', True)
                redirect_https = route.get('redirect-https', True)
                description = route.get('description', '')

                static_route = {
                    'domain': domain,
                    'target': target,
                    'https_enabled': https_enabled,
                    'redirect_https': redirect_https,
                    'description': description,
                    'type': 'static'
                }

                static_routes.append(static_route)
                logger.debug(f"Loaded static route: {domain} -> {target}")

        except Exception as e:
            logger.error(f"Failed to load static routes from {static_routes_file}: {e}")

        return static_routes

    def extract_snadboy_revp_labels(self, labels: Dict[str, str], container_name: str,
                                   host: str, port_mappings: Dict[str, str]) -> Dict[str, Any]:
        """Extract and parse snadboy.revp labels from container"""
        revp_config = {
            'enabled': False,
            'services': {}
        }

        # Resolve the SSH alias to actual hostname for service URL
        resolved_hostname = self._get_ssh_hostname(host)

        # Look for snadboy.revp.{PORT}.* labels
        revp_pattern = re.compile(r'^snadboy\.revp\.(\d+)\.(.+)$')
        port_configs = {}

        for label, value in labels.items():
            match = revp_pattern.match(label)
            if not match:
                continue

            port = match.group(1)
            setting = match.group(2)

            if port not in port_configs:
                port_configs[port] = {}
            port_configs[port][setting] = value

        if not port_configs:
            return revp_config

        revp_config['enabled'] = True

        # Process each port configuration
        for internal_port, config in port_configs.items():
            domain = config.get('domain')
            if not domain:
                # Track label parsing error for missing domain
                self.track_label_parsing_error(
                    container_name,
                    f"snadboy.revp.{internal_port}.*",
                    f"Missing required 'domain' label for port {internal_port}"
                )
                continue

            # Get external port mapping
            external_port = port_mappings.get(f"{internal_port}/tcp", internal_port)

            # Build service configuration
            backend_proto = config.get('backend-proto', 'http')
            backend_path = config.get('backend-path', '/')

            # Ensure backend_path starts with /
            if not backend_path.startswith('/'):
                backend_path = '/' + backend_path

            # HTTPS configuration
            https_enabled = config.get('https', 'true').lower() == 'true'
            redirect_https = config.get('redirect-https', 'true').lower() == 'true'
            cert_resolver = config.get('https-certresolver', 'letsencrypt')

            service_name = f"{container_name}-{internal_port}"
            service_url = f"{backend_proto}://{resolved_hostname}:{external_port}{backend_path}"

            revp_config['services'][service_name] = {
                'domain': domain,
                'service_url': service_url,
                'internal_port': internal_port,
                'external_port': external_port,
                'https_enabled': https_enabled,
                'redirect_https': redirect_https,
                'cert_resolver': cert_resolver
            }

        return revp_config

    def build_traefik_config(self, containers_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build complete Traefik configuration from container data"""
        logger.debug(f"Processing {len(containers_data)} containers for Traefik config")
        config = {
            'http': {
                'routers': {},
                'services': {}
                # Don't include empty middlewares - Traefik HTTP provider rejects it
            }
        }

        # Track middlewares separately
        middlewares = {}

        for container_data in containers_data:
            container = container_data.get('container', {})
            details = container_data.get('details', {})
            source_host = container_data.get('source_host', 'unknown')

            if not details:
                continue

            labels = details.get('Config', {}).get('Labels', {})

            # Ensure labels is a dict, not None
            if labels is None:
                logger.debug(f"Container has no labels (Labels is None)")
                labels = {}

            # Get container name
            raw_names = container.get('Names', ['/unknown'])
            logger.debug(f"Raw container names from SSH: {raw_names} (type: {type(raw_names)})")

            # Handle both array of names and single string name
            if isinstance(raw_names, list):
                container_name = raw_names[0].strip('/') if raw_names else 'unknown'
            elif isinstance(raw_names, str):
                container_name = raw_names.strip('/')
            else:
                container_name = 'unknown'

            # Debug: Show full container info
            logger.debug(f"Processing container: {container_name} (ID: {container.get('ID', 'unknown')[:12]}) from host: {source_host}")
            logger.debug(f"  Labels type: {type(labels)}, Labels count: {len(labels) if labels else 0}")

            # Container labels logging
            try:
                snadboy_labels = {k: v for k, v in labels.items() if k.startswith('snadboy.revp')}
            except Exception as e:
                logger.error(f"Error processing labels for container {container_name}: {e}")
                logger.debug(f"  Labels value: {labels}")
                # Track as excluded container due to label processing error
                self.track_excluded_container(
                    container,
                    "Label processing error",
                    source_host,
                    f"Exception: {str(e)}"
                )
                snadboy_labels = {}

            if snadboy_labels:
                logger.debug(f"  Found snadboy.revp labels:")
                for label, value in snadboy_labels.items():
                    logger.debug(f"    {label}={value}")

            # Get port mappings
            port_mappings = {}
            network_settings = details.get('NetworkSettings', {})
            ports = network_settings.get('Ports', {})
            for internal_port, mappings in ports.items():
                if mappings and len(mappings) > 0:
                    port_mappings[internal_port] = mappings[0].get('HostPort', internal_port.split('/')[0])

            # Process snadboy.revp labels
            try:
                revp_config = self.extract_snadboy_revp_labels(
                    labels, container_name, source_host, port_mappings
                )
            except Exception as e:
                logger.error(f"Error extracting snadboy.revp labels for container {container_name}: {e}")
                # Track as excluded container due to label extraction error
                self.track_excluded_container(
                    container,
                    "Label extraction error",
                    source_host,
                    f"Exception: {str(e)}"
                )
                # Continue with empty config (will be tracked as excluded)
                revp_config = {'enabled': False, 'services': {}}

            if revp_config['enabled']:
                for service_name, service_config in revp_config['services'].items():
                    logger.debug(f"  Creating service '{service_name}' -> {service_config['service_url']}")
                    logger.debug(f"    HTTPS: {service_config['https_enabled']}, Redirect: {service_config['redirect_https']}")

                    domain = service_config['domain']
                    https_enabled = service_config['https_enabled']
                    redirect_https = service_config['redirect_https']
                    # cert_resolver not needed - using wildcard certificate

                    # Create service (shared by all routers)
                    config['http']['services'][service_name] = {
                        'loadBalancer': {
                            'servers': [{
                                'url': service_config['service_url']
                            }]
                        }
                    }

                    if https_enabled and redirect_https:
                        # HTTPS with redirect: HTTP router redirects, HTTPS router serves

                        # Create HTTPS router
                        https_router_name = f"{service_name}-https-router"
                        config['http']['routers'][https_router_name] = {
                            'rule': f"Host(`{domain}`)",
                            'service': service_name,
                            'entryPoints': ['websecure'],
                            'tls': {}  # Uses wildcard certificate from dynamic config
                        }

                        # Create HTTP redirect router
                        http_router_name = f"{service_name}-http-router"
                        redirect_middleware_name = f"{service_name}-redirect-https"

                        middlewares[redirect_middleware_name] = {
                            'redirectScheme': {
                                'scheme': 'https',
                                'permanent': True
                            }
                        }

                        config['http']['routers'][http_router_name] = {
                            'rule': f"Host(`{domain}`)",
                            'service': service_name,
                            'entryPoints': ['web'],
                            'middlewares': [redirect_middleware_name]
                        }

                    elif https_enabled and not redirect_https:
                        # Both HTTP and HTTPS without redirect

                        # HTTP router
                        http_router_name = f"{service_name}-http-router"
                        config['http']['routers'][http_router_name] = {
                            'rule': f"Host(`{domain}`)",
                            'service': service_name,
                            'entryPoints': ['web']
                        }

                        # HTTPS router
                        https_router_name = f"{service_name}-https-router"
                        config['http']['routers'][https_router_name] = {
                            'rule': f"Host(`{domain}`)",
                            'service': service_name,
                            'entryPoints': ['websecure'],
                            'tls': {}  # Uses wildcard certificate from dynamic config
                        }

                    else:
                        # HTTP only
                        http_router_name = f"{service_name}-http-router"
                        config['http']['routers'][http_router_name] = {
                            'rule': f"Host(`{domain}`)",
                            'service': service_name,
                            'entryPoints': ['web']
                        }
            else:
                # Track excluded container
                snadboy_labels = {k: v for k, v in labels.items() if k.startswith('snadboy.revp')}
                if snadboy_labels:
                    # Has snadboy labels but configuration is invalid
                    self.track_excluded_container(
                        container,
                        "Invalid label configuration",
                        source_host,
                        f"Found labels: {list(snadboy_labels.keys())}"
                    )
                else:
                    # No snadboy labels
                    self.track_excluded_container(
                        container,
                        "No snadboy.revp labels",
                        source_host,
                        f"Container has {len(labels)} labels total, none with snadboy.revp prefix"
                    )

        # Process static routes
        static_routes = self._load_static_routes()
        for static_route in static_routes:
            domain = static_route['domain']
            target = static_route['target']
            https_enabled = static_route['https_enabled']
            redirect_https = static_route['redirect_https']

            logger.debug(f"Processing static route: {domain} -> {target}")
            logger.debug(f"  HTTPS: {https_enabled}, Redirect: {redirect_https}")

            # Generate unique service name for static route
            service_name = f"static-{domain.replace('.', '-').replace('*', 'wildcard')}"

            # Create service pointing to static target
            config['http']['services'][service_name] = {
                'loadBalancer': {
                    'servers': [{
                        'url': target
                    }]
                }
            }

            if https_enabled and redirect_https:
                # HTTPS with redirect: HTTP router redirects, HTTPS router serves

                # Create HTTPS router
                https_router_name = f"{service_name}-https-router"
                config['http']['routers'][https_router_name] = {
                    'rule': f"Host(`{domain}`)",
                    'service': service_name,
                    'entryPoints': ['websecure'],
                    'tls': {}  # Uses wildcard certificate from dynamic config
                }

                # Create HTTP redirect router
                http_router_name = f"{service_name}-http-router"
                redirect_middleware_name = f"{service_name}-redirect-https"

                middlewares[redirect_middleware_name] = {
                    'redirectScheme': {
                        'scheme': 'https',
                        'permanent': True
                    }
                }

                config['http']['routers'][http_router_name] = {
                    'rule': f"Host(`{domain}`)",
                    'service': service_name,
                    'entryPoints': ['web'],
                    'middlewares': [redirect_middleware_name]
                }

            elif https_enabled and not redirect_https:
                # Both HTTP and HTTPS without redirect

                # HTTP router
                http_router_name = f"{service_name}-http-router"
                config['http']['routers'][http_router_name] = {
                    'rule': f"Host(`{domain}`)",
                    'service': service_name,
                    'entryPoints': ['web']
                }

                # HTTPS router
                https_router_name = f"{service_name}-https-router"
                config['http']['routers'][https_router_name] = {
                    'rule': f"Host(`{domain}`)",
                    'service': service_name,
                    'entryPoints': ['websecure'],
                    'tls': {}  # Uses wildcard certificate from dynamic config
                }

            else:
                # HTTP only
                http_router_name = f"{service_name}-http-router"
                config['http']['routers'][http_router_name] = {
                    'rule': f"Host(`{domain}`)",
                    'service': service_name,
                    'entryPoints': ['web']
                }

        # Only add middlewares to config if we have any
        if middlewares:
            config['http']['middlewares'] = middlewares

        # Log configuration statistics
        stats = {
            'routers': len(config['http']['routers']),
            'services': len(config['http']['services']),
            'middlewares': len(middlewares),
            'static_routes': len(static_routes)
        }

        logger.info(f"Configuration built: {stats['routers']} routers, {stats['services']} services, {stats['middlewares']} middlewares, {stats['static_routes']} static routes")

        return config

    async def generate_config(self, host: Optional[str] = None, force_refresh: bool = False) -> Dict[str, Any]:
        """Generate complete Traefik configuration

        Args:
            host: Optional specific host to query
            force_refresh: Force bypass cache and do full discovery

        Returns:
            Traefik configuration dictionary
        """
        # Return cached config if available (and not forcing refresh)
        if not force_refresh:
            async with self._cache_lock:
                if self._config_cache is not None:
                    cache_age = time.time() - self._cache_timestamp
                    logger.debug(f"Returning cached config (age: {cache_age:.1f}s)")
                    return self._config_cache.copy()

        # Reset diagnostic tracking for fresh generation
        self.reset_diagnostics()
        start_time = time.time()
        if host:
            # Query specific host
            target_hosts = [host]
            logger.info(f"Generating config for specific host: {host}")
        else:
            # Query all enabled hosts
            all_hosts = self._get_enabled_hosts()
            target_hosts = all_hosts if all_hosts else [self.config.get('default_host')]
            logger.info(f"Generating config for all enabled hosts: {target_hosts}")

        containers_data = []
        for target_host in target_hosts:
            logger.debug(f"Discovering containers on host: {target_host}")
            # Check SSH host health during discovery
            await self.check_ssh_host_health(target_host)
            containers = await self.discover_containers(target_host)

            for container in containers:
                details = await self.inspect_container(target_host, container['ID'])
                containers_data.append({
                    'container': container,
                    'details': details,
                    'source_host': target_host
                })

        logger.info(f"Total containers discovered across all hosts: {len(containers_data)}")

        config = self.build_traefik_config(containers_data)

        # Store processed containers for API endpoints
        self.last_processed_containers = containers_data.copy()

        # Add enhanced metadata with diagnostic information
        end_time = time.time()
        processing_time_ms = int((end_time - start_time) * 1000)

        # Separate successful vs failed hosts
        hosts_successful = []
        hosts_failed = []
        for host in target_hosts:
            if host in self.ssh_host_status and self.ssh_host_status[host].get('status') == 'connected':
                hosts_successful.append(host)
            else:
                hosts_failed.append(host)

        # Count static routes
        static_routes_count = 0
        if self.config.get('enable_static_routes', False):
            static_routes = self._load_static_routes()
            static_routes_count = len(static_routes)

        config['_metadata'] = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'hosts_queried': target_hosts,
            'container_count': len(containers_data),
            'enabled_services': len(config['http']['services']),
            'processing_time_ms': processing_time_ms,
            'hosts_successful': hosts_successful,
            'hosts_failed': hosts_failed,
            'excluded_containers': len(self.excluded_containers),
            'static_routes': static_routes_count
        }

        # Update cache
        async with self._cache_lock:
            self._config_cache = config.copy()
            self._cache_timestamp = time.time()
            logger.info(f"Config cache updated ({processing_time_ms}ms generation time)")

        return config

    async def check_ssh_host_health(self, host: str) -> Dict[str, Any]:
        """Check SSH host connectivity and gather diagnostic info"""
        start_time = time.time()
        status = {
            'hostname': '',
            'status': 'unknown',
            'last_attempt': datetime.now(timezone.utc).isoformat(),
            'connection_time_ms': None,
            'error_count': 0,
            'last_error': None
        }

        try:
            # Get host configuration
            ssh_hosts_file = self.config.get('ssh_hosts_file', 'config/ssh-hosts.yaml')
            if os.path.exists(ssh_hosts_file):
                with open(ssh_hosts_file, 'r') as f:
                    ssh_config = yaml.safe_load(f)
                    host_config = ssh_config.get('hosts', {}).get(host, {})
                    status['hostname'] = host_config.get('hostname', host)

            # Test connection and gather info
            # Get all containers first, then filter for running ones
            all_containers = await self.ssh_client.list_containers(host=host)
            running_containers = [c for c in all_containers if 'up ' in c.get('Status', '').lower()]

            # Extract container names for diagnostics
            running_names = [c.get('Name', c.get('Names', 'unknown')) for c in running_containers]
            all_names = [c.get('Name', c.get('Names', 'unknown')) for c in all_containers]

            connection_time = int((time.time() - start_time) * 1000)
            status.update({
                'status': 'connected',
                'connection_time_ms': connection_time,
                'last_successful_connection': status['last_attempt'],
                'containers_total': len(all_containers),
                'containers_running': len(running_containers),
                'running_container_names': running_names,
                'all_container_names': all_names
            })

            # Try to get Docker version
            try:
                docker_info = await self.ssh_client.get_docker_info(host)
                status['docker_version'] = docker_info.get('ServerVersion', 'unknown')
            except Exception:
                pass  # Docker version is optional

        except Exception as e:
            connection_time = int((time.time() - start_time) * 1000)
            error_msg = str(e)

            # Determine error type
            if 'timeout' in error_msg.lower():
                error_type = 'timeout'
            elif 'permission' in error_msg.lower() or 'auth' in error_msg.lower():
                error_type = 'permission'
            elif 'connection refused' in error_msg.lower():
                error_type = 'unreachable'
            else:
                error_type = 'error'

            status.update({
                'status': error_type,
                'connection_time_ms': connection_time,
                'last_error': error_msg,
                'error_count': status.get('error_count', 0) + 1
            })

        # Update tracking
        self.ssh_host_status[host] = status
        return status

    async def get_all_ssh_host_status(self) -> Dict[str, Dict[str, Any]]:
        """Get health status for all configured SSH hosts"""
        enabled_hosts = self._get_enabled_hosts()
        status_results = {}

        for host in enabled_hosts:
            try:
                status_results[host] = await self.check_ssh_host_health(host)
            except Exception as e:
                logger.error(f"Failed to check host {host}: {e}")
                status_results[host] = {
                    'hostname': host,
                    'status': 'error',
                    'last_error': str(e),
                    'last_attempt': datetime.now(timezone.utc).isoformat()
                }

        return status_results

    def track_excluded_container(self, container: Dict[str, Any], reason: str, host: str, details: str = None):
        """Track a container that was excluded from routing"""
        # Extract container name properly
        raw_names = container.get('Names', container.get('Name', ''))
        if isinstance(raw_names, list):
            container_name = raw_names[0].strip('/') if raw_names else 'unknown'
        elif isinstance(raw_names, str):
            container_name = raw_names.strip('/')
        else:
            container_name = str(raw_names) if raw_names else 'unknown'

        excluded = {
            'id': container.get('ID', ''),
            'name': container_name,
            'image': container.get('Image', ''),
            'status': container.get('Status', ''),
            'state': container.get('State', 'unknown'),
            'created': container.get('Created'),
            'reason': reason,
            'host': host,
            'details': details
        }
        self.excluded_containers.append(excluded)
        logger.debug(f"Excluded container {excluded['name']} on {host}: {reason}")

    def track_label_parsing_error(self, container_name: str, label: str, error: str):
        """Track a label parsing error"""
        self.label_parsing_errors.append({
            'container': container_name,
            'label': label,
            'error': error
        })
        logger.warning(f"Label parsing error in {container_name}: {error}")

    def get_static_route_diagnostics(self) -> Dict[str, Any]:
        """Get static route loading diagnostics"""
        static_routes = []
        errors = []

        try:
            if not self.config.get('enable_static_routes', False):
                return {'loaded': 0, 'errors': ['Static routes disabled']}

            static_routes_file = self.config.get('static_routes_file', 'config/static-routes.yaml')
            if not os.path.exists(static_routes_file):
                errors.append(f"Static routes file not found: {static_routes_file}")
                return {'loaded': 0, 'errors': errors}

            with open(static_routes_file, 'r') as f:
                routes_config = yaml.safe_load(f)
                raw_routes = routes_config.get('static_routes', [])

                for route in raw_routes:
                    domain = route.get('domain')
                    target = route.get('target')

                    if not domain or not target:
                        errors.append(f"Invalid route config: {route}")
                        continue

                    static_routes.append(route)

        except Exception as e:
            errors.append(f"Failed to load static routes: {e}")

        return {
            'loaded': len(static_routes),
            'errors': errors
        }

    def get_ssh_diagnostics(self) -> Dict[str, Any]:
        """Get Tailscale SSH connection diagnostics"""
        enabled_hosts = self._get_enabled_hosts()
        reachable_hosts = len([h for h, s in self.ssh_host_status.items() if s.get('status') == 'connected'])

        timeouts = len([h for h, s in self.ssh_host_status.items() if s.get('status') == 'timeout'])
        permission_errors = len([h for h, s in self.ssh_host_status.items() if s.get('status') == 'permission'])

        return {
            'tailscale_authentication': True,
            'connection_timeouts': timeouts,
            'permission_errors': permission_errors,
            'hosts_configured': len(enabled_hosts),
            'hosts_reachable': reachable_hosts
        }

    def reset_diagnostics(self):
        """Reset diagnostic tracking data"""
        self.excluded_containers.clear()
        self.processing_errors.clear()
        self.label_parsing_errors.clear()
        self.last_processed_containers.clear()
        # Note: ssh_host_status is NOT cleared - it persists across generations

    async def start_event_listeners(self):
        """Start Docker event listeners for all enabled hosts"""
        enabled_hosts = self._get_enabled_hosts()
        logger.info(f"Starting event listeners for hosts: {enabled_hosts}")

        for host in enabled_hosts:
            if host not in self._event_listener_tasks:
                task = asyncio.create_task(self._event_listener_loop(host))
                self._event_listener_tasks[host] = task
                self._event_stats[host] = 0
                logger.info(f"Started event listener for host: {host}")

    async def stop_event_listeners(self):
        """Stop all Docker event listeners"""
        logger.info("Stopping event listeners...")
        self._shutdown_event.set()

        for host, task in self._event_listener_tasks.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.debug(f"Event listener for {host} cancelled successfully")

        self._event_listener_tasks.clear()
        logger.info("All event listeners stopped")

    async def _event_listener_loop(self, host: str):
        """Event listener loop for a specific host using properly formatted SSH command"""
        import json
        retry_delay = 1
        max_retry_delay = 60

        # Get SSH alias from config
        host_config = self.ssh_client.hosts_config.get_host_config(host)
        ssh_alias = f"{host_config.user}@{host_config.hostname}"

        while not self._shutdown_event.is_set():
            process = None
            try:
                logger.info(f"Starting Docker event stream for {host}")

                # Properly format the command - pass docker command as single string to SSH
                # This avoids the "docker events accepts no arguments" error
                cmd = ["ssh", ssh_alias, "docker events --format '{{json .}}'"]

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                logger.info(f"Connected to Docker events stream on {host}")

                # Read events from the process stdout
                while not self._shutdown_event.is_set():
                    line = await process.stdout.readline()
                    if not line:
                        # Stream ended
                        logger.warning(f"Event stream ended for {host}")
                        break

                    try:
                        event = json.loads(line.decode('utf-8').strip())
                        self._event_stats[host] += 1
                        await self._handle_docker_event(host, event)
                        retry_delay = 1  # Reset retry delay on successful event
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse event from {host}: {e}")
                        continue

            except asyncio.CancelledError:
                logger.info(f"Event listener for {host} cancelled")
                if process:
                    process.kill()
                    await process.wait()
                break
            except Exception as e:
                logger.error(f"Error in event listener for {host}: {e}", exc_info=True)
                try:
                    if process and process.stderr:
                        stderr = await process.stderr.read()
                        if stderr:
                            logger.error(f"SSH stderr from {host}: {stderr.decode('utf-8')}")
                except:
                    pass
                if process:
                    process.kill()
                    await process.wait()
                if not self._shutdown_event.is_set():
                    logger.info(f"Reconnecting to {host} in {retry_delay}s...")
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, max_retry_delay)

    async def _handle_docker_event(self, host: str, event: Dict[str, Any]):
        """Handle a Docker event and update cache if necessary"""
        event_type = event.get('Type')
        action = event.get('Action')

        # Only handle container events
        if event_type != 'container':
            return

        # Actions that should trigger cache refresh
        refresh_actions = {'start', 'stop', 'die', 'destroy', 'create', 'restart'}

        if action in refresh_actions:
            container_name = event.get('Actor', {}).get('Attributes', {}).get('name', 'unknown')
            logger.info(f"Container event on {host}: {action} - {container_name}")

            # Refresh cache in background (don't block event processing)
            asyncio.create_task(self._refresh_cache_from_event(host, action, container_name))

    async def _refresh_cache_from_event(self, host: str, action: str, container_name: str):
        """Refresh cache in response to a Docker event (with debouncing)"""
        logger.debug(f"Event received: {action} for {container_name} on {host}, scheduling debounced refresh")

        # Cancel any pending refresh
        if self._pending_refresh and not self._pending_refresh.done():
            self._pending_refresh.cancel()
            logger.debug("Cancelled pending refresh to batch with new event")

        # Schedule new refresh after debounce delay
        self._pending_refresh = asyncio.create_task(self._debounced_refresh())

    async def _debounced_refresh(self):
        """Perform the actual cache refresh after debounce delay"""
        try:
            # Wait for debounce period (additional events will cancel and reschedule this)
            await asyncio.sleep(self._refresh_debounce_seconds)

            # Perform the refresh
            logger.info(f"Debounce period complete, refreshing cache now")
            await self.generate_config(force_refresh=True)
            logger.info(f"Cache refreshed successfully after event(s)")
        except asyncio.CancelledError:
            # This is expected when events are batched
            logger.debug("Debounced refresh cancelled (batching more events)")
            raise
        except Exception as e:
            logger.error(f"Failed to refresh cache after event: {e}")

    def get_cache_info(self) -> Dict[str, Any]:
        """Get information about the current cache state"""
        return {
            'cached': self._config_cache is not None,
            'last_update': datetime.fromtimestamp(self._cache_timestamp, timezone.utc).isoformat() if self._cache_timestamp else None,
            'cache_age_seconds': int(time.time() - self._cache_timestamp) if self._cache_timestamp else None,
            'services_count': len(self._config_cache.get('http', {}).get('services', {})) if self._config_cache else 0
        }

    def get_event_listener_status(self) -> Dict[str, Any]:
        """Get status of all event listeners"""
        return {
            host: {
                'status': 'connected' if not task.done() else 'disconnected',
                'events_received': self._event_stats.get(host, 0)
            }
            for host, task in self._event_listener_tasks.items()
        }