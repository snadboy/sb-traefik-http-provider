#!/usr/bin/env python3
"""
Advanced Traefik configuration transformer with support for complex routing rules
"""

import re
import logging
from typing import Dict, Any, List, Optional, Tuple
from ipaddress import ip_address, ip_network

logger = logging.getLogger(__name__)

class TraefikTransformer:
    """Advanced transformer for Docker labels to Traefik configuration"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.label_prefix = self.config.get('label_prefix', 'traefik')
        
    def parse_rule(self, rule_string: str) -> str:
        """Parse and validate Traefik routing rule"""
        # Basic validation of rule syntax
        valid_matchers = ['Host', 'PathPrefix', 'Path', 'Method', 'Headers', 'Query', 'ClientIP']
        
        # Check if rule contains valid matchers
        for matcher in valid_matchers:
            if matcher in rule_string:
                return rule_string
        
        # If no valid matcher found, assume it's a hostname
        if '.' in rule_string:
            return f"Host(`{rule_string}`)"
        
        return rule_string
    
    def extract_port_from_expose(self, exposed_ports: Dict[str, Any]) -> str:
        """Extract the most likely port from Docker's ExposedPorts"""
        if not exposed_ports:
            return "80"
        
        # Priority order for common ports
        priority_ports = ['80/tcp', '8080/tcp', '3000/tcp', '8000/tcp', '5000/tcp', '443/tcp']
        
        for port in priority_ports:
            if port in exposed_ports:
                return port.split('/')[0]
        
        # Return first available port
        first_port = list(exposed_ports.keys())[0]
        return first_port.split('/')[0]
    
    def generate_service_name(self, container_name: str, labels: Dict[str, str]) -> str:
        """Generate a Traefik-friendly service name"""
        # Check if service name is explicitly defined
        service_label = f"{self.label_prefix}.http.services"
        
        for label in labels:
            if label.startswith(service_label):
                parts = label.split('.')
                if len(parts) > 3:
                    return parts[3]
        
        # Clean container name for use as service name
        clean_name = re.sub(r'[^a-zA-Z0-9-]', '-', container_name)
        return clean_name.lower()
    
    def parse_middlewares(self, labels: Dict[str, str]) -> Dict[str, Any]:
        """Parse middleware configurations from labels"""
        middlewares = {}
        middleware_prefix = f"{self.label_prefix}.http.middlewares"
        
        for label, value in labels.items():
            if not label.startswith(middleware_prefix):
                continue
            
            parts = label.replace(middleware_prefix + '.', '').split('.')
            if not parts:
                continue
            
            middleware_name = parts[0]
            if middleware_name not in middlewares:
                middlewares[middleware_name] = {}
            
            if len(parts) == 1:
                continue
            
            # Parse specific middleware types
            middleware_type = parts[1] if len(parts) > 1 else None
            
            if middleware_type == 'headers':
                if 'headers' not in middlewares[middleware_name]:
                    middlewares[middleware_name]['headers'] = {}
                
                if len(parts) > 2:
                    header_config = '.'.join(parts[2:])
                    middlewares[middleware_name]['headers'][header_config] = value
            
            elif middleware_type == 'ratelimit':
                if 'rateLimit' not in middlewares[middleware_name]:
                    middlewares[middleware_name]['rateLimit'] = {}
                
                if len(parts) > 2:
                    rate_config = parts[2]
                    middlewares[middleware_name]['rateLimit'][rate_config] = value
            
            elif middleware_type == 'basicauth':
                middlewares[middleware_name]['basicAuth'] = {
                    'users': value.split(',')
                }
            
            elif middleware_type == 'compress':
                middlewares[middleware_name]['compress'] = True
            
            elif middleware_type == 'redirectscheme':
                if 'redirectScheme' not in middlewares[middleware_name]:
                    middlewares[middleware_name]['redirectScheme'] = {}
                
                if len(parts) > 2:
                    middlewares[middleware_name]['redirectScheme'][parts[2]] = value
            
            elif middleware_type == 'retry':
                if 'retry' not in middlewares[middleware_name]:
                    middlewares[middleware_name]['retry'] = {}
                
                if len(parts) > 2:
                    middlewares[middleware_name]['retry'][parts[2]] = value
            
            elif middleware_type == 'stripprefix':
                middlewares[middleware_name]['stripPrefix'] = {
                    'prefixes': value.split(',')
                }
            
            elif middleware_type == 'addprefix':
                middlewares[middleware_name]['addPrefix'] = {
                    'prefix': value
                }
        
        return middlewares
    
    def build_load_balancer(self, 
                           container_details: Dict[str, Any],
                           service_config: Dict[str, Any]) -> Dict[str, Any]:
        """Build load balancer configuration for a service"""
        network_settings = container_details.get('NetworkSettings', {})
        
        # Determine the best IP address to use
        ip_address = self._get_container_ip(network_settings)
        
        # Get port from service config or auto-detect
        port = service_config.get('port')
        if not port:
            exposed_ports = container_details.get('Config', {}).get('ExposedPorts', {})
            port = self.extract_port_from_expose(exposed_ports)
        
        scheme = service_config.get('scheme', 'http')
        
        load_balancer = {
            'servers': [{
                'url': f"{scheme}://{ip_address}:{port}"
            }]
        }
        
        # Add additional load balancer settings if present
        if 'healthCheck' in service_config:
            load_balancer['healthCheck'] = service_config['healthCheck']
        
        if 'sticky' in service_config:
            load_balancer['sticky'] = service_config['sticky']
        
        return {'loadBalancer': load_balancer}
    
    def _get_container_ip(self, network_settings: Dict[str, Any]) -> str:
        """Get the most appropriate IP address for the container"""
        networks = network_settings.get('Networks', {})
        
        # Priority order for network selection
        priority_networks = ['traefik', 'web', 'bridge']
        
        for network_name in priority_networks:
            if network_name in networks:
                network_info = networks[network_name]
                if network_info.get('IPAddress'):
                    return network_info['IPAddress']
        
        # Fall back to any available network
        for network_info in networks.values():
            if network_info.get('IPAddress'):
                return network_info['IPAddress']
        
        # Last resort: use legacy IPAddress field
        return network_settings.get('IPAddress', '127.0.0.1')
    
    def validate_config(self, config: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate generated Traefik configuration"""
        errors = []
        
        if 'http' not in config:
            errors.append("Missing 'http' section in configuration")
            return False, errors
        
        http_config = config['http']
        
        # Validate routers
        if 'routers' in http_config:
            for router_name, router_config in http_config['routers'].items():
                if 'rule' not in router_config:
                    errors.append(f"Router '{router_name}' missing 'rule' field")
                
                if 'service' in router_config:
                    service_name = router_config['service']
                    if service_name not in http_config.get('services', {}):
                        errors.append(f"Router '{router_name}' references non-existent service '{service_name}'")
        
        # Validate services
        if 'services' in http_config:
            for service_name, service_config in http_config['services'].items():
                if 'loadBalancer' not in service_config:
                    errors.append(f"Service '{service_name}' missing 'loadBalancer' configuration")
                elif 'servers' not in service_config['loadBalancer']:
                    errors.append(f"Service '{service_name}' missing 'servers' in loadBalancer")
                elif not service_config['loadBalancer']['servers']:
                    errors.append(f"Service '{service_name}' has empty 'servers' list")
        
        # Validate middlewares references
        if 'routers' in http_config:
            available_middlewares = set(http_config.get('middlewares', {}).keys())
            for router_name, router_config in http_config['routers'].items():
                if 'middlewares' in router_config:
                    for middleware in router_config['middlewares']:
                        if middleware not in available_middlewares:
                            errors.append(f"Router '{router_name}' references non-existent middleware '{middleware}'")
        
        return len(errors) == 0, errors
    
    def add_default_middlewares(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Add commonly used default middlewares"""
        if 'middlewares' not in config['http']:
            config['http']['middlewares'] = {}
        
        # Add security headers middleware
        if 'secure-headers' not in config['http']['middlewares']:
            config['http']['middlewares']['secure-headers'] = {
                'headers': {
                    'frameDeny': True,
                    'sslRedirect': True,
                    'browserXssFilter': True,
                    'contentTypeNosniff': True,
                    'stsIncludeSubdomains': True,
                    'stsPreload': True,
                    'stsSeconds': 31536000
                }
            }
        
        # Add rate limiting middleware
        if 'rate-limit' not in config['http']['middlewares']:
            config['http']['middlewares']['rate-limit'] = {
                'rateLimit': {
                    'average': 100,
                    'burst': 50
                }
            }
        
        # Add compression middleware
        if 'compress' not in config['http']['middlewares']:
            config['http']['middlewares']['compress'] = {
                'compress': {}
            }
        
        return config
    
    def merge_configs(self, configs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge multiple Traefik configurations"""
        merged = {
            'http': {
                'routers': {},
                'services': {},
                'middlewares': {}
            }
        }
        
        for config in configs:
            if 'http' in config:
                http_config = config['http']
                
                # Merge routers
                if 'routers' in http_config:
                    for name, router in http_config['routers'].items():
                        if name in merged['http']['routers']:
                            logger.warning(f"Router '{name}' already exists, overwriting")
                        merged['http']['routers'][name] = router
                
                # Merge services
                if 'services' in http_config:
                    for name, service in http_config['services'].items():
                        if name in merged['http']['services']:
                            logger.warning(f"Service '{name}' already exists, overwriting")
                        merged['http']['services'][name] = service
                
                # Merge middlewares
                if 'middlewares' in http_config:
                    for name, middleware in http_config['middlewares'].items():
                        if name in merged['http']['middlewares']:
                            logger.warning(f"Middleware '{name}' already exists, overwriting")
                        merged['http']['middlewares'][name] = middleware
        
        return merged