"""
Flask API routes for Traefik HTTP Provider
"""

import asyncio
import logging
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from app.core import TraefikProvider

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')

# Create Blueprint
api = Blueprint('api', __name__)

# Global provider instance
provider = None


def get_provider():
    """Get or create provider instance"""
    global provider
    if provider is None:
        provider = TraefikProvider()
    return provider


@api.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    logger.debug("Health check requested")
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'log_level': logger.level
    })


@api.route('/api/traefik/config', methods=['GET'])
def get_traefik_config():
    """Main endpoint for Traefik HTTP provider"""
    host = request.args.get('host')
    provider = get_provider()
    target_host = host or provider.config.get('default_host', 'unknown')

    logger.info(f"Configuration request received for host: {host or 'default'} -> using: {target_host}")
    logger.debug("About to call provider.generate_config")
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


@api.route('/api/containers', methods=['GET'])
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


@api.route('/api/config', methods=['GET'])
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