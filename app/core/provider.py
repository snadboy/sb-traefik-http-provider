"""
Traefik HTTP Provider using snadboy-ssh-docker
"""

import asyncio
import os
import yaml
import logging
import re
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from pathlib import Path
from snadboy_ssh_docker import SSHDockerClient

logger = logging.getLogger(__name__)


class TraefikProvider:
    """Manages Docker discovery and Traefik configuration generation"""

    def __init__(self, config_file: str = "config/provider-config.yaml"):
        self.config_file = config_file
        self.config = self._load_config()
        self.ssh_client = None
        self._initialize_client()

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
        """Initialize SSH Docker client"""
        try:
            ssh_hosts_file = self.config.get('ssh_hosts_file', 'config/ssh-hosts.yaml')
            ssh_hosts_path = Path(ssh_hosts_file)
            self.ssh_client = SSHDockerClient(config_file=ssh_hosts_path)
            logger.info("SSH Docker client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize SSH client: {e}")
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

    async def discover_containers(self, host: Optional[str] = None) -> List[Dict[str, Any]]:
        """Discover running containers on specified host"""
        target_host = host or self.config.get('default_host')
        if not target_host:
            raise ValueError("No host specified and no default_host in config")

        try:
            containers = await self.ssh_client.list_containers(
                host=target_host,
                filters={"STATUS": "running"}
            )
            logger.info(f"Discovered {len(containers)} running containers on {target_host}")
            return containers
        except Exception as e:
            logger.error(f"Failed to discover containers on {target_host}: {e}")
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

    def extract_snadboy_revp_labels(self, labels: Dict[str, str], container_name: str,
                                   host: str, port_mappings: Dict[str, str]) -> Dict[str, Any]:
        """Extract and parse snadboy.revp labels from container"""
        revp_config = {
            'enabled': False,
            'services': {}
        }

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
                continue

            # Get external port mapping
            external_port = port_mappings.get(f"{internal_port}/tcp", internal_port)

            # Build service configuration
            backend_proto = config.get('backend-proto', 'http')
            backend_path = config.get('backend-path', '/')

            # Ensure backend_path starts with /
            if not backend_path.startswith('/'):
                backend_path = '/' + backend_path

            service_name = f"{container_name}-{internal_port}"
            service_url = f"{backend_proto}://{host}:{external_port}{backend_path}"

            revp_config['services'][service_name] = {
                'domain': domain,
                'service_url': service_url,
                'internal_port': internal_port,
                'external_port': external_port
            }

        return revp_config

    def build_traefik_config(self, containers_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build complete Traefik configuration from container data"""
        logger.debug(f"Processing {len(containers_data)} containers for Traefik config")
        config = {
            'http': {
                'routers': {},
                'services': {},
                'middlewares': {}
            }
        }

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
            revp_config = self.extract_snadboy_revp_labels(
                labels, container_name, source_host, port_mappings
            )

            if revp_config['enabled']:
                for service_name, service_config in revp_config['services'].items():
                    logger.debug(f"  Creating service '{service_name}' -> {service_config['service_url']}")

                    # Create router
                    router_name = f"{service_name}-router"
                    config['http']['routers'][router_name] = {
                        'rule': f"Host(`{service_config['domain']}`)",
                        'service': service_name,
                        'entryPoints': ['web']
                    }

                    # Create service
                    config['http']['services'][service_name] = {
                        'loadBalancer': {
                            'servers': [{
                                'url': service_config['service_url']
                            }]
                        }
                    }

        # Log configuration statistics
        stats = {
            'routers': len(config['http']['routers']),
            'services': len(config['http']['services']),
            'middlewares': len(config['http']['middlewares'])
        }

        logger.info(f"Configuration built: {stats['routers']} routers, {stats['services']} services, {stats['middlewares']} middlewares")

        return config

    async def generate_config(self, host: Optional[str] = None) -> Dict[str, Any]:
        """Generate complete Traefik configuration"""
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

        # Add metadata
        config['_metadata'] = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'hosts_queried': target_hosts,
            'container_count': len(containers_data),
            'enabled_services': len(config['http']['services'])
        }

        return config