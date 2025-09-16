"""
FastAPI main application entry point for Traefik HTTP Provider
"""

import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.fastapi_routes import router, get_provider
from app.utils.logging_config import initialize_logging, get_logger

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
    # Initialize provider on startup
    provider = get_provider()
    logger.info(f"Provider initialized with config: {provider.config_file}")
    yield
    # Shutdown
    logger.info("FastAPI application shutting down")


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