#!/usr/bin/env python3
"""
Centralized logging configuration for Traefik HTTP Provider
Supports console output, file output with rotation, and structured logging
"""

import logging
import logging.handlers
import sys
import os
from pathlib import Path
from datetime import datetime
import json
from typing import Dict, Any, Optional

class ColoredFormatter(logging.Formatter):
    """Custom formatter with color support for console output"""
    
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record):
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.RESET}"
        return super().format(record)

class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging"""
    
    def format(self, record):
        log_obj = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Add exception info if present
        if record.exc_info:
            log_obj['exception'] = self.formatException(record.exc_info)
        
        # Add extra fields if present
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'created', 'filename', 'funcName',
                          'levelname', 'levelno', 'lineno', 'module', 'msecs',
                          'message', 'pathname', 'process', 'processName', 'relativeCreated',
                          'thread', 'threadName', 'exc_info', 'exc_text', 'stack_info']:
                log_obj[key] = value
        
        return json.dumps(log_obj)

class LoggerConfig:
    """Manages logging configuration for the application"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.log_dir = Path(self.config.get('log_dir', '/var/log/traefik-provider'))
        self.log_level = self.config.get('log_level', 'INFO')
        self.enable_console = self.config.get('enable_console', True)
        self.enable_file = self.config.get('enable_file', True)
        self.enable_json = self.config.get('enable_json', False)
        self.max_bytes = self.config.get('max_bytes', 10 * 1024 * 1024)  # 10MB
        self.backup_count = self.config.get('backup_count', 5)
        
        # Create log directory if it doesn't exist
        if self.enable_file:
            self.log_dir.mkdir(parents=True, exist_ok=True)
    
    def setup_logging(self, logger_name: Optional[str] = None) -> logging.Logger:
        """Configure and return a logger instance"""
        logger = logging.getLogger(logger_name or 'traefik-provider')
        logger.setLevel(getattr(logging, self.log_level.upper()))
        
        # Remove existing handlers
        logger.handlers = []
        
        # Console handler
        if self.enable_console:
            console_handler = self._create_console_handler()
            logger.addHandler(console_handler)
        
        # File handlers
        if self.enable_file:
            # Main log file
            file_handler = self._create_file_handler('app.log')
            logger.addHandler(file_handler)
            
            # Error log file (ERROR and above)
            error_handler = self._create_file_handler('error.log', level=logging.ERROR)
            logger.addHandler(error_handler)
            
            # Access log file
            access_handler = self._create_file_handler('access.log')
            access_logger = logging.getLogger('access')
            access_logger.addHandler(access_handler)
            access_logger.setLevel(logging.INFO)
        
        return logger
    
    def _create_console_handler(self) -> logging.StreamHandler:
        """Create console handler with colored output"""
        handler = logging.StreamHandler(sys.stdout)
        
        if self.enable_json:
            handler.setFormatter(JSONFormatter())
        else:
            formatter = ColoredFormatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
        
        handler.setLevel(getattr(logging, self.log_level.upper()))
        return handler
    
    def _create_file_handler(self, filename: str, level: Optional[int] = None) -> logging.handlers.RotatingFileHandler:
        """Create rotating file handler"""
        file_path = self.log_dir / filename
        handler = logging.handlers.RotatingFileHandler(
            file_path,
            maxBytes=self.max_bytes,
            backupCount=self.backup_count
        )
        
        if self.enable_json:
            handler.setFormatter(JSONFormatter())
        else:
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
        
        handler.setLevel(level or getattr(logging, self.log_level.upper()))
        return handler
    
    def get_access_logger(self) -> logging.Logger:
        """Get logger for access logs"""
        return logging.getLogger('access')
    
    def get_error_logger(self) -> logging.Logger:
        """Get logger for error logs"""
        return logging.getLogger('error')
    
    def get_audit_logger(self) -> logging.Logger:
        """Get logger for audit logs"""
        audit_logger = logging.getLogger('audit')
        if self.enable_file:
            audit_handler = self._create_file_handler('audit.log')
            audit_logger.addHandler(audit_handler)
            audit_logger.setLevel(logging.INFO)
        return audit_logger

class RequestLogger:
    """Middleware for logging HTTP requests"""
    
    def __init__(self, app, logger: logging.Logger):
        self.app = app
        self.logger = logger
    
    def log_request(self, request, response, duration: float):
        """Log HTTP request details"""
        log_data = {
            'method': request.method,
            'path': request.path,
            'remote_addr': request.remote_addr,
            'user_agent': request.user_agent.string,
            'status': response.status_code,
            'duration_ms': round(duration * 1000, 2),
            'query_params': dict(request.args),
        }
        
        if response.status_code >= 400:
            self.logger.warning(f"Request failed: {request.method} {request.path}", extra=log_data)
        else:
            self.logger.info(f"Request: {request.method} {request.path}", extra=log_data)

class ContainerDiscoveryLogger:
    """Specialized logger for container discovery events"""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
    
    def log_discovery_start(self, host: str):
        """Log start of container discovery"""
        self.logger.info(f"Starting container discovery on host: {host}", extra={'host': host, 'event': 'discovery_start'})
    
    def log_discovery_complete(self, host: str, container_count: int, duration: float):
        """Log completion of container discovery"""
        self.logger.info(
            f"Container discovery complete on {host}: found {container_count} containers in {duration:.2f}s",
            extra={
                'host': host,
                'container_count': container_count,
                'duration_seconds': duration,
                'event': 'discovery_complete'
            }
        )
    
    def log_container_found(self, host: str, container_name: str, container_id: str, labels: Dict[str, str]):
        """Log individual container discovery"""
        traefik_enabled = labels.get('traefik.enable', 'false').lower() == 'true'
        self.logger.debug(
            f"Found container: {container_name} on {host} (Traefik: {traefik_enabled})",
            extra={
                'host': host,
                'container_name': container_name,
                'container_id': container_id,
                'traefik_enabled': traefik_enabled,
                'event': 'container_found'
            }
        )
    
    def log_discovery_error(self, host: str, error: Exception):
        """Log container discovery error"""
        self.logger.error(
            f"Container discovery failed on {host}: {str(error)}",
            extra={
                'host': host,
                'error_type': type(error).__name__,
                'error_message': str(error),
                'event': 'discovery_error'
            },
            exc_info=True
        )

class ConfigurationLogger:
    """Specialized logger for configuration generation"""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
    
    def log_config_generation_start(self):
        """Log start of configuration generation"""
        self.logger.info("Starting Traefik configuration generation", extra={'event': 'config_generation_start'})
    
    def log_config_generation_complete(self, stats: Dict[str, int]):
        """Log completion of configuration generation"""
        self.logger.info(
            f"Configuration generated: {stats.get('routers', 0)} routers, "
            f"{stats.get('services', 0)} services, {stats.get('middlewares', 0)} middlewares",
            extra={
                'routers': stats.get('routers', 0),
                'services': stats.get('services', 0),
                'middlewares': stats.get('middlewares', 0),
                'event': 'config_generation_complete'
            }
        )
    
    def log_label_parsing(self, container_name: str, label_count: int):
        """Log label parsing for a container"""
        self.logger.debug(
            f"Parsing {label_count} labels for container: {container_name}",
            extra={
                'container_name': container_name,
                'label_count': label_count,
                'event': 'label_parsing'
            }
        )
    
    def log_validation_error(self, errors: list):
        """Log configuration validation errors"""
        for error in errors:
            self.logger.error(
                f"Configuration validation error: {error}",
                extra={
                    'error': error,
                    'event': 'validation_error'
                }
            )

# Global logger configuration instance
_logger_config = None

def initialize_logging(config: Optional[Dict[str, Any]] = None) -> LoggerConfig:
    """Initialize global logging configuration"""
    global _logger_config
    _logger_config = LoggerConfig(config)
    return _logger_config

def get_logger(name: str) -> logging.Logger:
    """Get a configured logger instance"""
    if _logger_config is None:
        initialize_logging()
    
    logger = logging.getLogger(name)
    if not logger.handlers:
        _logger_config.setup_logging(name)
    
    return logger

def get_discovery_logger() -> ContainerDiscoveryLogger:
    """Get container discovery logger"""
    return ContainerDiscoveryLogger(get_logger('discovery'))

def get_config_logger() -> ConfigurationLogger:
    """Get configuration generation logger"""
    return ConfigurationLogger(get_logger('configuration'))

# Configure root logger
def configure_root_logger(level: str = 'INFO'):
    """Configure the root logger"""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )