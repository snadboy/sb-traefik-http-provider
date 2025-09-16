"""
Main application entry point for Traefik HTTP Provider
"""

import os
import logging
from flask import Flask
from flask_cors import CORS
from app.api.routes import api
from app.utils.logging_config import initialize_logging, get_logger

# Initialize logging
logging_config = {
    'log_level': os.getenv('LOG_LEVEL', 'INFO'),
    'enable_json': os.getenv('LOG_JSON', 'false').lower() == 'true',
    'log_dir': os.getenv('LOG_DIR', '/var/log/traefik-provider')
}
initialize_logging(logging_config)
logger = get_logger(__name__)

# Set up basic logging first
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=True
)
logger.setLevel(getattr(logging, log_level))
logger.info(f"Logger initialized with level: {log_level}")


def create_app():
    """Create and configure Flask application"""
    app = Flask(__name__)

    # Enable CORS for Traefik access
    CORS(app)

    # Register blueprints
    app.register_blueprint(api)

    logger.info("Flask application created successfully")
    return app


# Create application instance
app = create_app()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Traefik HTTP Provider Server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8080, help='Port to listen on')
    parser.add_argument('--config', default='config/provider-config.yaml', help='Provider config file')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--log-dir', default='/var/log/traefik-provider', help='Log directory')
    parser.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='Log level')
    parser.add_argument('--log-json', action='store_true', help='Enable JSON logging')

    args = parser.parse_args()

    if args.debug:
        app.debug = True
        logger.info("Debug mode enabled")

    # Set environment variables for provider config
    os.environ['PROVIDER_CONFIG'] = args.config

    logger.info(f"Starting Traefik HTTP Provider on {args.host}:{args.port}")
    logger.info(f"Log directory: {args.log_dir}")
    logger.info(f"Log level: {args.log_level if not args.debug else 'DEBUG'}")
    logger.info(f"JSON logging: {'enabled' if args.log_json else 'disabled'}")

    app.run(host=args.host, port=args.port, debug=args.debug)