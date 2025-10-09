"""
FastAPI main application entry point for Traefik HTTP Provider
"""

import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.routes import router, get_provider
from app.utils.logging_config import initialize_logging, get_logger
from app.utils.ssh_setup import initialize_ssh_known_hosts
from app.utils.dns_health import perform_dns_health_check

# Initialize logging
logging_config = {
    'log_level': os.getenv('LOG_LEVEL', 'INFO'),
    'enable_json': os.getenv('LOG_JSON', 'false').lower() == 'true',
    'log_dir': os.getenv('LOG_DIR', '/var/log/traefik-provider')
}
initialize_logging(logging_config)
logger = get_logger(__name__)

# Set up basic logging
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=True
)
logger.setLevel(getattr(logging, log_level))
logger.info(f"Logger initialized with level: {log_level}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    # Startup
    logger.info("FastAPI application starting up")

    # DNS health check (optional, controlled by env var)
    if os.getenv('DNS_HEALTH_CHECK_ENABLED', 'false').lower() == 'true':
        logger.info("Performing DNS health check...")
        dns_result = perform_dns_health_check()
        if dns_result['ok']:
            logger.info(f"DNS health check PASSED: {dns_result['checks']}")
        else:
            logger.error(f"DNS health check FAILED: {dns_result['errors']}")
            if os.getenv('DNS_HEALTH_CHECK_STRICT', 'false').lower() == 'true':
                logger.error("DNS health check is in strict mode - startup aborted")
                raise RuntimeError(f"DNS health check failed: {dns_result['errors']}")
            else:
                logger.warning("DNS health check failed but continuing startup (non-strict mode)")
    else:
        logger.debug("DNS health check disabled (set DNS_HEALTH_CHECK_ENABLED=true to enable)")

    # Initialize SSH known_hosts for Tailscale hosts
    # This runs once during application startup, after Docker networking is fully ready
    logger.info("Initializing SSH known_hosts for configured Tailscale hosts")
    ssh_result = initialize_ssh_known_hosts()
    if ssh_result["status"] == "completed":
        logger.info(f"SSH initialization: {ssh_result['message']}")
        if ssh_result["hosts_failed"] > 0:
            logger.warning(f"Some SSH hosts failed to initialize. Use POST /api/ssh/scan-keys/<hostname> to retry manually.")
    else:
        logger.warning(f"SSH initialization skipped: {ssh_result.get('message', 'Unknown reason')}")

    # Initialize provider on startup
    provider = get_provider()
    logger.info(f"Provider initialized with config: {provider.config_file}")

    # Do initial config generation to populate cache
    logger.info("Performing initial configuration generation...")
    initial_config = await provider.generate_config(force_refresh=True)
    services_count = len(initial_config.get('http', {}).get('services', {}))
    logger.info(f"Initial configuration generated: {services_count} services discovered")

    # Start Docker event listeners for real-time updates
    logger.info("Starting Docker event listeners...")
    await provider.start_event_listeners()
    logger.info("Event listeners started successfully")

    yield

    # Shutdown
    logger.info("FastAPI application shutting down")
    await provider.stop_event_listeners()
    logger.info("Event listeners stopped")


def create_app() -> FastAPI:
    """Create and configure FastAPI application"""
    app = FastAPI(
        title="Traefik HTTP Provider",
        description="Dynamic HTTP provider for Traefik using SSH Docker discovery",
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json"
    )

    # Configure CORS for Traefik access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Allow all origins for Traefik
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routes
    app.include_router(router)

    # Add custom exception handler for better error responses
    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "http": {"routers": {}, "services": {}, "middlewares": {}}
            }
        )

    logger.info("FastAPI application created successfully")
    return app


# Create application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser(description='Traefik HTTP Provider Server (FastAPI)')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8080, help='Port to listen on')
    parser.add_argument('--config', default='config/provider-config.yaml', help='Provider config file')
    parser.add_argument('--workers', type=int, default=1, help='Number of worker processes')
    parser.add_argument('--reload', action='store_true', help='Enable auto-reload for development')
    parser.add_argument('--log-level', default='INFO',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       help='Log level')
    parser.add_argument('--log-dir', default='/var/log/traefik-provider', help='Log directory')
    parser.add_argument('--log-json', action='store_true', help='Enable JSON logging')

    args = parser.parse_args()

    # Set environment variables for provider config
    os.environ['PROVIDER_CONFIG'] = args.config
    if args.log_json:
        os.environ['LOG_JSON'] = 'true'
    os.environ['LOG_LEVEL'] = args.log_level
    os.environ['LOG_DIR'] = args.log_dir

    logger.info(f"Starting Traefik HTTP Provider (FastAPI) on {args.host}:{args.port}")
    logger.info(f"Workers: {args.workers}")
    logger.info(f"Log directory: {args.log_dir}")
    logger.info(f"Log level: {args.log_level}")
    logger.info(f"JSON logging: {'enabled' if args.log_json else 'disabled'}")

    uvicorn.run(
        "app.fastapi_main:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
        reload=args.reload,
        log_level=args.log_level.lower(),
        access_log=True
    )