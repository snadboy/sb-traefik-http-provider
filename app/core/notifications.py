"""
Notification Service

Sends notifications via Gotify when services change status.
"""

import asyncio
import logging
import os
import time
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import yaml

from .health_checker import ServiceHealth, HealthStatus

logger = logging.getLogger(__name__)


class NotificationService:
    """Manages notifications via Gotify"""

    def __init__(self, config_path: str = 'config/notifications.yaml'):
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self._enabled = False
        self._gotify_url: Optional[str] = None
        self._gotify_token: Optional[str] = None
        self._default_priority = 5

        # Rate limiting / cooldowns
        self._last_notification: Dict[str, float] = {}  # service -> timestamp
        self._cooldown_seconds = 300  # 5 minutes default

        # Crash loop detection
        self._restart_events: Dict[str, list] = {}  # service -> list of timestamps
        self._crash_loop_window = 300  # 5 minutes
        self._crash_loop_threshold = 3  # 3 restarts in window

        self._load_config()

    def _load_config(self):
        """Load notification configuration"""
        if not os.path.exists(self.config_path):
            logger.info(f"Notifications config not found at {self.config_path}, notifications disabled")
            self._enabled = False
            return

        try:
            with open(self.config_path, 'r') as f:
                self.config = yaml.safe_load(f) or {}

            notifications = self.config.get('notifications', {})
            self._enabled = notifications.get('enabled', False)

            if not self._enabled:
                logger.info("Notifications disabled in config")
                return

            # Gotify configuration
            gotify = notifications.get('gotify', {})
            self._gotify_url = gotify.get('url')
            self._gotify_token = gotify.get('token')

            # Support environment variable for token
            if self._gotify_token and self._gotify_token.startswith('${') and self._gotify_token.endswith('}'):
                env_var = self._gotify_token[2:-1]
                self._gotify_token = os.environ.get(env_var)
                if not self._gotify_token:
                    logger.warning(f"Gotify token env var {env_var} not set")

            self._default_priority = gotify.get('priority', 5)

            # Rules configuration
            rules = notifications.get('rules', {})

            health_failed = rules.get('health_check_failed', {})
            self._cooldown_seconds = health_failed.get('cooldown', 300)

            crash_loop = rules.get('crash_loop', {})
            self._crash_loop_threshold = crash_loop.get('threshold', 3)
            self._crash_loop_window = crash_loop.get('window', 300)

            if self._gotify_url and self._gotify_token:
                logger.info(f"Notifications enabled via Gotify at {self._gotify_url}")
            else:
                logger.warning("Gotify URL or token not configured, notifications disabled")
                self._enabled = False

        except Exception as e:
            logger.error(f"Failed to load notifications config: {e}")
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def reload_config(self):
        """Reload configuration from file"""
        self._load_config()

    async def send_notification(
        self,
        title: str,
        message: str,
        priority: Optional[int] = None,
        extras: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Send a notification via Gotify"""
        if not self._enabled:
            logger.debug(f"Notifications disabled, skipping: {title}")
            return False

        if not self._gotify_url or not self._gotify_token:
            logger.warning("Gotify not configured")
            return False

        try:
            url = f"{self._gotify_url.rstrip('/')}/message"
            headers = {
                'X-Gotify-Key': self._gotify_token,
                'Content-Type': 'application/json'
            }

            payload = {
                'title': title,
                'message': message,
                'priority': priority or self._default_priority
            }

            if extras:
                payload['extras'] = extras

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                    ssl=False
                ) as response:
                    if response.status == 200:
                        logger.info(f"Notification sent: {title}")
                        return True
                    else:
                        text = await response.text()
                        logger.error(f"Gotify returned {response.status}: {text}")
                        return False

        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
            return False

    def _check_cooldown(self, service_name: str) -> bool:
        """Check if we're in cooldown period for this service"""
        last = self._last_notification.get(service_name, 0)
        if time.time() - last < self._cooldown_seconds:
            return True  # In cooldown
        return False

    def _update_cooldown(self, service_name: str):
        """Update last notification time for service"""
        self._last_notification[service_name] = time.time()

    async def notify_health_change(
        self,
        service_name: str,
        health: ServiceHealth,
        old_status: HealthStatus,
        notify_priority: int = 5
    ):
        """Notify about a service health status change"""
        if not self._enabled:
            return

        # Check if notifications are enabled for this transition
        rules = self.config.get('notifications', {}).get('rules', {})

        if health.status == HealthStatus.DOWN:
            rule = rules.get('health_check_failed', {})
            if not rule.get('enabled', True):
                return

            # Check cooldown
            if self._check_cooldown(service_name):
                logger.debug(f"Skipping notification for {service_name} - in cooldown")
                return

            priority = rule.get('priority', notify_priority)
            title = f"🔴 Service Down: {service_name}"
            message = (
                f"Service {service_name} is DOWN\n\n"
                f"Error: {health.error_message or 'Unknown'}\n"
                f"Last success: {health.last_success.isoformat() if health.last_success else 'Never'}\n"
                f"Consecutive failures: {health.consecutive_failures}"
            )

            await self.send_notification(title, message, priority)
            self._update_cooldown(service_name)

        elif health.status == HealthStatus.UP and old_status in (HealthStatus.DOWN, HealthStatus.DEGRADED):
            rule = rules.get('service_recovered', {})
            if not rule.get('enabled', True):
                return

            priority = rule.get('priority', 3)
            title = f"🟢 Service Recovered: {service_name}"
            message = (
                f"Service {service_name} is back UP\n\n"
                f"Response time: {health.response_time_ms}ms\n"
                f"Was down since: {health.last_failure.isoformat() if health.last_failure else 'Unknown'}"
            )

            await self.send_notification(title, message, priority)
            # Clear cooldown on recovery
            self._last_notification.pop(service_name, None)

        elif health.status == HealthStatus.DEGRADED and old_status == HealthStatus.UP:
            # Optional: notify on degradation
            rule = rules.get('service_degraded', {})
            if not rule.get('enabled', False):  # Disabled by default
                return

            priority = rule.get('priority', 4)
            title = f"🟡 Service Degraded: {service_name}"
            message = (
                f"Service {service_name} is responding slowly\n\n"
                f"Response time: {health.response_time_ms}ms\n"
                f"Threshold: {health.response_time_ms}ms"
            )

            await self.send_notification(title, message, priority)

    async def notify_container_event(
        self,
        container_name: str,
        event: str,
        host: str,
        notify_priority: int = 5
    ):
        """Notify about container events (crash loops, unexpected stops)"""
        if not self._enabled:
            return

        rules = self.config.get('notifications', {}).get('rules', {})

        # Track restart events for crash loop detection
        if event in ('start', 'restart'):
            if container_name not in self._restart_events:
                self._restart_events[container_name] = []

            self._restart_events[container_name].append(time.time())

            # Clean old events outside window
            cutoff = time.time() - self._crash_loop_window
            self._restart_events[container_name] = [
                t for t in self._restart_events[container_name]
                if t > cutoff
            ]

            # Check for crash loop
            if len(self._restart_events[container_name]) >= self._crash_loop_threshold:
                rule = rules.get('crash_loop', {})
                if not rule.get('enabled', True):
                    return

                # Check cooldown
                if self._check_cooldown(f"crashloop-{container_name}"):
                    return

                priority = rule.get('priority', 9)
                title = f"🔄 Crash Loop Detected: {container_name}"
                message = (
                    f"Container {container_name} on {host} is crash-looping\n\n"
                    f"Restarts in last {self._crash_loop_window}s: {len(self._restart_events[container_name])}\n"
                    f"Threshold: {self._crash_loop_threshold}"
                )

                await self.send_notification(title, message, priority)
                self._update_cooldown(f"crashloop-{container_name}")

                # Clear events after notification
                self._restart_events[container_name] = []

        elif event == 'die':
            # Could notify on unexpected container death
            # For now, rely on health checks to detect this
            pass

    def get_status(self) -> Dict[str, Any]:
        """Get notification service status"""
        return {
            'enabled': self._enabled,
            'gotify_url': self._gotify_url,
            'gotify_configured': bool(self._gotify_url and self._gotify_token),
            'cooldown_seconds': self._cooldown_seconds,
            'crash_loop_threshold': self._crash_loop_threshold,
            'crash_loop_window': self._crash_loop_window,
            'services_in_cooldown': [
                name for name, ts in self._last_notification.items()
                if time.time() - ts < self._cooldown_seconds
            ]
        }
