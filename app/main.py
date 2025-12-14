"""
FastAPI main application entry point for Traefik HTTP Provider
"""

import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from app.api.routes import router, get_provider
from app.utils.logging_config import initialize_logging, get_logger
from app.utils.ssh_setup import initialize_ssh_known_hosts
from app.utils.dns_health import perform_dns_health_check
from app.core.health_checker import HealthChecker
from app.core.notifications import NotificationService

# Global instances for health checker and notifications
health_checker: HealthChecker = None
notification_service: NotificationService = None


def get_health_checker() -> HealthChecker:
    """Get the global health checker instance"""
    global health_checker
    return health_checker


def get_notification_service() -> NotificationService:
    """Get the global notification service instance"""
    global notification_service
    return notification_service


def _build_health_services_list(provider) -> list:
    """Build list of services to monitor from provider data"""
    services = []

    # Get container services from provider's last processed data
    for container_data in provider.last_processed_containers:
        details = container_data.get('details', {})
        labels = details.get('Config', {}).get('Labels', {}) or {}

        # Look for health path in labels
        for key, value in labels.items():
            if key.startswith('snadboy.revp.') and key.endswith('.health'):
                # Extract port from label key
                port = key.split('.')[2]
                domain_key = f"snadboy.revp.{port}.domain"
                domain = labels.get(domain_key)

                if domain and value:
                    # Get the first domain if comma-separated
                    primary_domain = domain.split(',')[0].strip().split(':')[0]
                    # Build health URL using the public domain
                    health_url = f"https://{primary_domain}{value}"
                    services.append({
                        'name': primary_domain,
                        'health_url': health_url,
                        'type': 'container'
                    })

    # Get static routes with health paths
    static_routes = provider._load_static_routes()
    for route in static_routes:
        if route.get('health_path'):
            # For static routes, hit the backend directly (internal)
            target = route['target'].rstrip('/')
            health_url = f"{target}{route['health_path']}"
            services.append({
                'name': route['domain'],
                'health_url': health_url,
                'type': 'static'
            })

    return services


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
    logger.info("Provider initialized successfully")

    # Do initial config generation to populate cache
    logger.info("Performing initial configuration generation...")
    initial_config = await provider.generate_config(force_refresh=True)
    services_count = len(initial_config.get('http', {}).get('services', {}))
    logger.info(f"Initial configuration generated: {services_count} services discovered")

    # Start Docker event listeners for real-time updates
    logger.info("Starting Docker event listeners...")
    await provider.start_event_listeners()
    logger.info("Event listeners started successfully")

    # Initialize notification service
    global notification_service
    notification_service = NotificationService()
    logger.info(f"Notification service initialized (enabled: {notification_service.enabled})")

    # Initialize health checker
    global health_checker
    health_check_interval = int(os.getenv('HEALTH_CHECK_INTERVAL', '60'))
    health_checker = HealthChecker(check_interval=health_check_interval)

    # Register notification callback for health status changes
    if notification_service.enabled:
        health_checker.register_status_change_callback(
            lambda name, health, old_status: notification_service.notify_health_change(
                name, health, old_status,
                notify_priority=5  # Default, will be overridden per-service
            )
        )

    # Build list of services to monitor from initial config
    services_to_monitor = _build_health_services_list(provider)
    health_checker.update_services(services_to_monitor)

    # Start health checker
    await health_checker.start()
    logger.info(f"Health checker started (interval: {health_check_interval}s, services: {len(services_to_monitor)})")

    yield

    # Shutdown
    logger.info("FastAPI application shutting down")

    # Stop health checker
    if health_checker:
        await health_checker.stop()
        logger.info("Health checker stopped")

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

    # Mount static files for dashboard at root
    # Order matters: API routes are registered first via include_router,
    # then static files are mounted last as a catch-all
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(static_dir):
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
        logger.info(f"Mounted static files at / from: {static_dir}")
    else:
        logger.warning(f"Static directory not found: {static_dir}")

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