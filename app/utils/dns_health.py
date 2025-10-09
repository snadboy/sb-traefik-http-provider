"""
DNS Health Check Module for Technitium DNS

Validates DNS resolution and optionally HTTP connectivity to Technitium DNS server.
Can be run as a startup check and exposed via API.
"""

import os
import logging
from typing import Dict, Any, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import json
import dns.resolver  # dnspython

logger = logging.getLogger(__name__)


class DNSHealthCheck:
    """DNS health checker for Technitium DNS server"""

    def __init__(
        self,
        name: str = None,
        ns_ts: str = None,
        ns_lan: str = None,
        admin_url: str = None,
        timeout: float = 2.0,
        # Notification settings
        gotify_enabled: bool = None,
        gotify_url: str = None,
        gotify_token: str = None,
        gotify_title: str = None,
        gotify_priority: int = None
    ):
        """Initialize DNS health checker

        Args:
            name: Domain name to test (e.g., sonarr.isnadboy.com)
            ns_ts: Tailscale nameserver IP (required)
            ns_lan: LAN nameserver IP (optional)
            admin_url: Technitium admin URL for HTTP check (optional)
            timeout: Query timeout in seconds
            gotify_enabled: Enable Gotify notifications
            gotify_url: Gotify message URL
            gotify_token: Gotify app token
            gotify_title: Gotify notification title
            gotify_priority: Gotify message priority
        """
        self.name = name or os.getenv("DNS_CHECK_NAME", "sonarr.isnadboy.com")
        self.ns_ts = ns_ts or os.getenv("DNS_CHECK_NS_TS", "100.65.231.21")
        self.ns_lan = ns_lan or os.getenv("DNS_CHECK_NS_LAN", "")
        self.admin_url = admin_url or os.getenv("DNS_CHECK_ADMIN_URL", "")
        self.timeout = timeout

        # Notification configuration
        self.gotify_enabled = gotify_enabled if gotify_enabled is not None else os.getenv("GOTIFY_ENABLED", "false").lower() == "true"
        self.gotify_url = gotify_url or os.getenv("GOTIFY_URL", "")
        self.gotify_token = gotify_token or os.getenv("GOTIFY_TOKEN", "")
        self.gotify_title = gotify_title or os.getenv("GOTIFY_TITLE", "DNS Health Check FAILED")
        self.gotify_priority = gotify_priority or int(os.getenv("GOTIFY_PRIORITY", "5"))

    def query_a(self, server: str, name: str) -> bool:
        """Query A record from DNS server

        Args:
            server: DNS server IP
            name: Domain name to query

        Returns:
            True if query successful and has answers
        """
        try:
            resolver = dns.resolver.Resolver(configure=False)
            resolver.nameservers = [server]
            resolver.timeout = resolver.lifetime = self.timeout

            answers = resolver.resolve(name, "A", tcp=False)  # UDP for speed
            has_results = any(a.address for a in answers)

            if has_results:
                logger.debug(f"DNS query successful: {name} @ {server}")
            return has_results

        except dns.exception.Timeout:
            logger.warning(f"DNS query timeout: {name} @ {server}")
            return False
        except dns.resolver.NXDOMAIN:
            logger.warning(f"DNS domain not found: {name} @ {server}")
            return False
        except Exception as e:
            logger.error(f"DNS query failed: {name} @ {server}: {e}")
            return False

    def http_ok(self, url: str) -> bool:
        """Check if HTTP(S) URL is accessible

        Args:
            url: URL to check

        Returns:
            True if HTTP status is 2xx or 3xx
        """
        try:
            with urlopen(url, timeout=self.timeout) as resp:
                is_ok = 200 <= resp.status < 400
                if is_ok:
                    logger.debug(f"HTTP check successful: {url}")
                return is_ok
        except (URLError, HTTPError) as e:
            logger.warning(f"HTTP check failed: {url}: {e}")
            return False
        except Exception as e:
            logger.error(f"HTTP check error: {url}: {e}")
            return False

    def _http_post(self, url: str, data: bytes, headers: Optional[Dict[str, str]] = None, timeout: float = 3) -> bool:
        """Internal HTTP POST helper

        Args:
            url: URL to POST to
            data: Request body (JSON encoded)
            headers: Request headers
            timeout: Request timeout

        Returns:
            True if POST succeeded (2xx status)
        """
        if headers is None:
            headers = {}
        try:
            req = Request(url, data=data, headers=headers)
            with urlopen(req, timeout=timeout) as resp:
                return 200 <= resp.status < 300
        except Exception as e:
            logger.debug(f"HTTP POST failed to {url}: {e}")
            return False

    def notify(self, message: str) -> bool:
        """Send notification via Gotify

        Args:
            message: Notification message

        Returns:
            True if notification sent successfully
        """
        if not self.gotify_enabled:
            logger.debug("Gotify notifications disabled")
            return False

        if not self.gotify_url or not self.gotify_token:
            logger.warning("Gotify enabled but URL or token not configured")
            return False

        try:
            data = json.dumps({
                "title": self.gotify_title,
                "message": message,
                "priority": self.gotify_priority
            }).encode()
            headers = {
                "Content-Type": "application/json",
                "X-Gotify-Key": self.gotify_token
            }
            if self._http_post(self.gotify_url, data, headers):
                logger.info("Sent notification via Gotify")
                return True
        except Exception as e:
            logger.warning(f"Failed to send Gotify notification: {e}")

        return False

    def perform_check(self) -> Dict[str, Any]:
        """Perform complete DNS health check

        Returns:
            Dictionary with check results:
            {
                'ok': bool,
                'checks': {
                    'tailscale_dns': bool,
                    'lan_dns': bool (if configured),
                    'admin_http': bool (if configured)
                },
                'details': {
                    'name': str,
                    'ns_ts': str,
                    'ns_lan': str,
                    'admin_url': str
                },
                'errors': [str, ...]
            }
        """
        checks = {}
        errors = []

        # Check Tailscale DNS (required)
        logger.info(f"Checking Tailscale DNS: {self.name} @ {self.ns_ts}")
        ts_ok = self.query_a(self.ns_ts, self.name)
        checks['tailscale_dns'] = ts_ok
        if not ts_ok:
            errors.append(f"Tailscale DNS query failed: {self.name} @ {self.ns_ts}")

        # Check LAN DNS (optional)
        if self.ns_lan:
            logger.info(f"Checking LAN DNS: {self.name} @ {self.ns_lan}")
            lan_ok = self.query_a(self.ns_lan, self.name)
            checks['lan_dns'] = lan_ok
            if not lan_ok:
                errors.append(f"LAN DNS query failed: {self.name} @ {self.ns_lan}")

        # Check Admin HTTP (optional)
        if self.admin_url:
            logger.info(f"Checking Admin HTTP: {self.admin_url}")
            admin_ok = self.http_ok(self.admin_url)
            checks['admin_http'] = admin_ok
            if not admin_ok:
                errors.append(f"Admin HTTP check failed: {self.admin_url}")

        # Overall result: all configured checks must pass
        all_ok = all(checks.values())

        result = {
            'ok': all_ok,
            'checks': checks,
            'details': {
                'name': self.name,
                'ns_ts': self.ns_ts,
                'ns_lan': self.ns_lan or None,
                'admin_url': self.admin_url or None
            },
            'errors': errors
        }

        if all_ok:
            logger.info("DNS health check PASSED")
        else:
            logger.warning(f"DNS health check FAILED: {errors}")

        return result


# Singleton instance for module-level access
_health_checker: Optional[DNSHealthCheck] = None


def get_dns_health_checker() -> DNSHealthCheck:
    """Get or create DNS health checker singleton"""
    global _health_checker
    if _health_checker is None:
        _health_checker = DNSHealthCheck()
    return _health_checker


def perform_dns_health_check(send_notification: bool = False) -> Dict[str, Any]:
    """Perform DNS health check using module singleton

    Args:
        send_notification: If True, send notification on failure

    Returns:
        Health check result dictionary
    """
    checker = get_dns_health_checker()
    result = checker.perform_check()

    # Send notification if check failed and notifications are enabled
    if send_notification and not result['ok']:
        message = f"DNS health check FAILED for {checker.name} (TS:{checker.ns_ts}, LAN:{checker.ns_lan or '-'}, ADMIN:{checker.admin_url or '-'})\nErrors: {', '.join(result['errors'])}"
        checker.notify(message)

    return result
