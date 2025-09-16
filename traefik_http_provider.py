#!/usr/bin/env python3
"""
Traefik HTTP Provider using snadboy-ssh-docker
Discovers Docker containers across SSH hosts and provides Traefik configuration
"""

import asyncio
import time
from typing import Dict, Any, List, Optional
from flask import Flask, jsonify, request, g
from flask_cors import CORS
import yaml
from datetime import datetime
from snadboy_ssh_docker import SSHDockerClient
import os
import sys

# Import enhanced logging configuration
from logging_config import (
    initialize_logging, get_logger, get_discovery_logger,
    get_config_logger, RequestLogger
)

# Initialize logging with environment variables
import os
import logging

# Set up basic logging first
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=True
)

# Then initialize our custom logging
logging_config = {
    'log_level': os.getenv('LOG_LEVEL', 'INFO'),
    'enable_json': os.getenv('LOG_JSON', 'false').lower() == 'true',
    'log_dir': os.getenv('LOG_DIR', '/var/log/traefik-provider')
}
initialize_logging(logging_config)
logger = get_logger(__name__)
logger.setLevel(getattr(logging, log_level))

logger.info(f"Logger initialized with level: {log_level}")
discovery_logger = get_discovery_logger()
config_logger = get_config_logger()
audit_logger = get_logger('audit')

app = Flask(__name__)
CORS(app)  # Enable CORS for Traefik access

class TraefikProvider:
    """Manages Docker discovery and Traefik configuration generation"""
    
    def __init__(self, config_file: str = "provider-config.yaml"):
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
            'ssh_hosts_file': 'ssh-hosts.yaml',
            'default_host': None,
            'enable_tls': False,
            'default_rule_type': 'Host',
            'network_mode': 'bridge',
            'refresh_interval': 30
        }
    
    def _initialize_client(self):
        """Initialize SSH Docker client"""
        try:
            from pathlib import Path
            ssh_hosts_file = self.config.get('ssh_hosts_file', 'ssh-hosts.yaml')
            # Convert to Path object
            ssh_hosts_path = Path(ssh_hosts_file)
            self.ssh_client = SSHDockerClient(config_file=ssh_hosts_path)
            logger.info("SSH Docker client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize SSH client: {e}")
            raise

    def _get_enabled_hosts(self) -> List[str]:
        """Get list of enabled hosts from SSH hosts configuration"""
        try:
            import yaml
            ssh_hosts_file = self.config.get('ssh_hosts_file', 'ssh-hosts.yaml')
            if not os.path.exists(ssh_hosts_file):
                logger.warning(f"SSH hosts file {ssh_hosts_file} not found")
                return []

            with open(ssh_hosts_file, 'r') as f:
                ssh_config = yaml.safe_load(f)

            enabled_hosts = []
            hosts = ssh_config.get('hosts', {})
            for host_name, host_config in hosts.items():
                if host_config.get('enabled', True):  # Default to enabled if not specified
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
    

    def extract_snadboy_revp_labels(self, labels: Dict[str, str], container_name: str, host: str, port_mappings: Dict[str, str]) -> Dict[str, Any]:
        """Extract and parse snadboy.revp labels from container"""
        import re

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
                continue  # Skip ports without domain

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

            # Get container name - handle both array and string formats
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

            # Get port mappings for snadboy.revp labels
            port_mappings = {}
            network_settings = details.get('NetworkSettings', {})
            ports = network_settings.get('Ports', {})
            for internal_port, mappings in ports.items():
                if mappings and len(mappings) > 0:
                    port_mappings[internal_port] = mappings[0].get('HostPort', internal_port.split('/')[0])

            # Get host information
            target_host = self.config.get('default_host')

            # Process snadboy.revp labels
            revp_config = self.extract_snadboy_revp_labels(labels, container_name, target_host, port_mappings)

            if revp_config['enabled']:
                # Process snadboy.revp configuration
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
        
        config_logger.log_config_generation_complete(stats)
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
                    'source_host': target_host  # Track which host this came from
                })

        logger.info(f"Total containers discovered across all hosts: {len(containers_data)}")

        config = self.build_traefik_config(containers_data)
        
        # Add metadata
        config['_metadata'] = {
            'generated_at': datetime.utcnow().isoformat(),
            'host': target_host,
            'container_count': len(containers),
            'enabled_services': len(config['http']['services'])
        }
        
        return config

# Global provider instance
provider = None

def get_provider():
    """Get or create provider instance"""
    global provider
    if provider is None:
        provider = TraefikProvider()
    return provider

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    logger.debug("Health check requested")
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'log_level': logger.level
    })

@app.route('/api/traefik/config', methods=['GET'])
def get_traefik_config():
    """Main endpoint for Traefik HTTP provider"""
    host = request.args.get('host')
    provider = get_provider()
    target_host = host or provider.config.get('default_host', 'unknown')
    logger.info(f"Configuration request received for host: {host or 'default'} -> using: {target_host}")
    logger.info(f"TRACE: About to call provider.generate_config")
    audit_logger.info(f"Config API called - host: {host}, client: {request.remote_addr}")
    
    try:
        # Run async function in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        config = loop.run_until_complete(provider.generate_config(host))
        loop.close()

        # Show generated configuration
        logger.debug(f"Generated routers: {list(config['http']['routers'].keys())}")
        logger.debug(f"Generated services: {list(config['http']['services'].keys())}")

        service_count = len(config['http']['services'])
        target_host = host or provider.config.get('default_host', 'unknown')
        logger.info(f"Successfully generated config with {service_count} services for host: {target_host}")
        audit_logger.info(f"Config generated successfully - {service_count} services")
        
        return jsonify(config)
    except ValueError as e:
        logger.error(f"Invalid request: {e}")
        audit_logger.error(f"Config generation failed - invalid request: {e}")
        return jsonify({
            'error': str(e),
            'http': {'routers': {}, 'services': {}, 'middlewares': {}}
        }), 400
    except Exception as e:
        logger.error(f"Failed to generate config: {e}", exc_info=True)
        audit_logger.error(f"Config generation failed with exception: {e}")
        return jsonify({
            'error': 'Internal server error',
            'http': {'routers': {}, 'services': {}, 'middlewares': {}}
        }), 500

@app.route('/api/containers', methods=['GET'])
def list_containers():
    """Debug endpoint to list discovered containers"""
    host = request.args.get('host')
    logger.info(f"Container list requested for host: {host or 'default'}")
    
    try:
        provider = get_provider()
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        containers = loop.run_until_complete(provider.discover_containers(host))
        loop.close()
        
        target_host = host or provider.config.get('default_host')
        logger.info(f"Returning {len(containers)} containers from {target_host}")
        
        return jsonify({
            'host': target_host,
            'count': len(containers),
            'containers': containers
        })
    except Exception as e:
        logger.error(f"Failed to list containers: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/config', methods=['GET'])
def get_provider_config():
    """Get current provider configuration"""
    logger.debug("Provider configuration requested")
    audit_logger.info(f"Configuration viewed by {request.remote_addr}")
    
    provider = get_provider()
    # Sanitize sensitive information
    safe_config = provider.config.copy()
    if 'ssh_hosts_file' in safe_config:
        safe_config['ssh_hosts_file'] = '***hidden***'
    
    return jsonify(safe_config)

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Traefik HTTP Provider Server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8080, help='Port to listen on')
    parser.add_argument('--config', default='provider-config.yaml', help='Provider config file')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--log-dir', default='/var/log/traefik-provider', help='Log directory')
    parser.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='Log level')
    parser.add_argument('--log-json', action='store_true', help='Enable JSON logging')
    
    args = parser.parse_args()
    
    # Reconfigure logging with command-line arguments
    log_config = {
        'log_dir': args.log_dir,
        'log_level': args.log_level if not args.debug else 'DEBUG',
        'enable_json': args.log_json,
        'enable_console': True,
        'enable_file': True
    }
    # Re-initialize logging with new config
    from logging_config import LoggerConfig
    global_config = LoggerConfig(
        log_dir=log_config['log_dir'],
        log_level=log_config['log_level'],
        enable_json=log_config['enable_json'],
        enable_console=log_config['enable_console'],
        enable_file=log_config['enable_file']
    )
    logger = global_config.setup_logging(__name__)
    
    if args.debug:
        app.debug = True
        logger.info("Debug mode enabled")
    
    # Initialize provider with specified config
    logger.info(f"Initializing provider with config file: {args.config}")
    provider = TraefikProvider(config_file=args.config)
    
    logger.info(f"Starting Traefik HTTP Provider on {args.host}:{args.port}")
    logger.info(f"Log directory: {args.log_dir}")
    logger.info(f"Log level: {args.log_level if not args.debug else 'DEBUG'}")
    logger.info(f"JSON logging: {'enabled' if args.log_json else 'disabled'}")
    audit_logger.info(f"Provider started on {args.host}:{args.port}")
    
    app.run(host=args.host, port=args.port, debug=args.debug)