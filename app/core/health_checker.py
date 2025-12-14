"""
Health Checker Service

Periodically polls service health endpoints and tracks status.
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from enum import Enum
import aiohttp

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    """Service health status"""
    UNKNOWN = "unknown"
    UP = "up"
    DOWN = "down"
    DEGRADED = "degraded"  # Responding but slow


class ServiceHealth:
    """Tracks health state for a single service"""

    def __init__(self, service_name: str, health_url: str):
        self.service_name = service_name
        self.health_url = health_url
        self.status = HealthStatus.UNKNOWN
        self.last_check: Optional[datetime] = None
        self.last_success: Optional[datetime] = None
        self.last_failure: Optional[datetime] = None
        self.response_time_ms: Optional[int] = None
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.error_message: Optional[str] = None
        self.http_status: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'service_name': self.service_name,
            'health_url': self.health_url,
            'status': self.status.value,
            'last_check': self.last_check.isoformat() if self.last_check else None,
            'last_success': self.last_success.isoformat() if self.last_success else None,
            'last_failure': self.last_failure.isoformat() if self.last_failure else None,
            'response_time_ms': self.response_time_ms,
            'consecutive_failures': self.consecutive_failures,
            'consecutive_successes': self.consecutive_successes,
            'error_message': self.error_message,
            'http_status': self.http_status
        }


class HealthChecker:
    """Manages health checking for all services"""

    def __init__(
        self,
        check_interval: int = 60,
        timeout: int = 5,
        degraded_threshold_ms: int = 3000,
        failure_threshold: int = 3
    ):
        self.check_interval = check_interval  # seconds between checks
        self.timeout = timeout  # HTTP request timeout
        self.degraded_threshold_ms = degraded_threshold_ms  # response time to consider degraded
        self.failure_threshold = failure_threshold  # consecutive failures before DOWN

        self._services: Dict[str, ServiceHealth] = {}
        self._check_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._on_status_change_callbacks: List[callable] = []

    def register_status_change_callback(self, callback: callable):
        """Register a callback to be called when service status changes"""
        self._on_status_change_callbacks.append(callback)

    def update_services(self, services: List[Dict[str, Any]]):
        """Update the list of services to monitor"""
        new_service_names = set()

        for svc in services:
            service_name = svc.get('name')
            health_url = svc.get('health_url')

            if not service_name or not health_url:
                continue

            new_service_names.add(service_name)

            if service_name not in self._services:
                self._services[service_name] = ServiceHealth(service_name, health_url)
                logger.info(f"Added health monitoring for: {service_name} -> {health_url}")
            else:
                # Update URL if changed
                if self._services[service_name].health_url != health_url:
                    self._services[service_name].health_url = health_url
                    logger.info(f"Updated health URL for {service_name}: {health_url}")

        # Remove services that are no longer present
        removed = set(self._services.keys()) - new_service_names
        for name in removed:
            del self._services[name]
            logger.info(f"Removed health monitoring for: {name}")

    async def start(self):
        """Start the health checker background task"""
        if self._check_task is not None:
            logger.warning("Health checker already running")
            return

        self._shutdown_event.clear()
        self._check_task = asyncio.create_task(self._check_loop())
        logger.info(f"Health checker started (interval: {self.check_interval}s)")

    async def stop(self):
        """Stop the health checker"""
        if self._check_task is None:
            return

        logger.info("Stopping health checker...")
        self._shutdown_event.set()
        self._check_task.cancel()

        try:
            await self._check_task
        except asyncio.CancelledError:
            pass

        self._check_task = None
        logger.info("Health checker stopped")

    async def _check_loop(self):
        """Main health check loop"""
        while not self._shutdown_event.is_set():
            try:
                await self._check_all_services()
            except Exception as e:
                logger.error(f"Error in health check loop: {e}", exc_info=True)

            # Wait for next check interval
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self.check_interval
                )
                break  # Shutdown requested
            except asyncio.TimeoutError:
                pass  # Normal timeout, continue checking

    async def _check_all_services(self):
        """Check health of all registered services"""
        if not self._services:
            return

        logger.debug(f"Checking health of {len(self._services)} services")

        # Check all services concurrently
        tasks = [
            self._check_service(name, health)
            for name, health in self._services.items()
        ]

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_service(self, name: str, health: ServiceHealth):
        """Check health of a single service"""
        old_status = health.status

        try:
            start_time = time.time()

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    health.health_url,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                    ssl=False  # Skip SSL verification for internal checks
                ) as response:
                    elapsed_ms = int((time.time() - start_time) * 1000)

                    health.last_check = datetime.now(timezone.utc)
                    health.response_time_ms = elapsed_ms
                    health.http_status = response.status

                    # 2xx or 401/403 (auth required but service is up)
                    if response.status < 400 or response.status in (401, 403):
                        health.last_success = health.last_check
                        health.consecutive_failures = 0
                        health.consecutive_successes += 1
                        health.error_message = None

                        if elapsed_ms > self.degraded_threshold_ms:
                            health.status = HealthStatus.DEGRADED
                        else:
                            health.status = HealthStatus.UP
                    else:
                        await self._handle_failure(
                            health,
                            f"HTTP {response.status}"
                        )

        except asyncio.TimeoutError:
            await self._handle_failure(health, "Timeout")
        except aiohttp.ClientConnectorError as e:
            await self._handle_failure(health, f"Connection error: {e}")
        except Exception as e:
            await self._handle_failure(health, f"Error: {e}")

        # Notify if status changed
        if health.status != old_status:
            logger.info(f"Service {name} status changed: {old_status.value} -> {health.status.value}")
            await self._notify_status_change(name, health, old_status)

    async def _handle_failure(self, health: ServiceHealth, error: str):
        """Handle a health check failure"""
        health.last_check = datetime.now(timezone.utc)
        health.last_failure = health.last_check
        health.consecutive_failures += 1
        health.consecutive_successes = 0
        health.error_message = error

        if health.consecutive_failures >= self.failure_threshold:
            health.status = HealthStatus.DOWN
        elif health.status == HealthStatus.UP:
            # Don't immediately mark as down, could be transient
            health.status = HealthStatus.DEGRADED

    async def _notify_status_change(
        self,
        name: str,
        health: ServiceHealth,
        old_status: HealthStatus
    ):
        """Notify callbacks of status change"""
        for callback in self._on_status_change_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(name, health, old_status)
                else:
                    callback(name, health, old_status)
            except Exception as e:
                logger.error(f"Error in status change callback: {e}")

    def get_health_status(self) -> Dict[str, Any]:
        """Get current health status of all services"""
        services_status = {
            name: health.to_dict()
            for name, health in self._services.items()
        }

        # Summary counts
        total = len(self._services)
        up = sum(1 for h in self._services.values() if h.status == HealthStatus.UP)
        down = sum(1 for h in self._services.values() if h.status == HealthStatus.DOWN)
        degraded = sum(1 for h in self._services.values() if h.status == HealthStatus.DEGRADED)
        unknown = sum(1 for h in self._services.values() if h.status == HealthStatus.UNKNOWN)

        return {
            'summary': {
                'total': total,
                'up': up,
                'down': down,
                'degraded': degraded,
                'unknown': unknown
            },
            'services': services_status,
            'check_interval': self.check_interval,
            'last_full_check': max(
                (h.last_check for h in self._services.values() if h.last_check),
                default=None
            )
        }

    def get_service_health(self, service_name: str) -> Optional[Dict[str, Any]]:
        """Get health status for a specific service"""
        if service_name in self._services:
            return self._services[service_name].to_dict()
        return None

    async def check_now(self, service_name: Optional[str] = None):
        """Trigger an immediate health check"""
        if service_name:
            if service_name in self._services:
                await self._check_service(
                    service_name,
                    self._services[service_name]
                )
        else:
            await self._check_all_services()
