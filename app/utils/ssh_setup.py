"""
SSH setup utilities for Tailscale SSH authentication
Handles SSH known_hosts population for remote Docker hosts

SECURITY NOTE — TAILSCALE DEPENDENCY
====================================
This module contains a `refresh_ssh_keys()` function that will REMOVE and
REPLACE existing known_hosts entries for a host when its key changes
(e.g. after a VM rebuild or unclean shutdown that regenerates host keys).

This auto-refresh behavior is safe ONLY because this provider is deployed
on a Tailscale network, where peer identity is already established via
WireGuard + Tailscale's own node key exchange. The SSH host key check is
effectively a second layer on top of an already-authenticated transport.

If this provider is ever deployed WITHOUT Tailscale (e.g. on a raw LAN or
across the public internet), the auto-refresh behavior in `refresh_ssh_keys`
and the auto-recovery path in `provider.discover_containers` MUST be
disabled — otherwise a MITM attacker on the network could inject a rogue
host key and be silently trusted. Search this file for "TAILSCALE-DEPENDENT"
to find the affected code paths.
"""

import os
import subprocess
import time
import yaml
from typing import Dict, List, Any
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


def scan_and_add_ssh_keys(hostname: str, timeout: int = 15, retries: int = 3) -> Dict[str, Any]:
    """
    Scan SSH host keys for a given hostname and add to known_hosts

    Args:
        hostname: The hostname to scan (e.g., 'fabric', 'media-arr')
        timeout: Timeout for ssh-keyscan command in seconds
        retries: Number of retry attempts if scanning fails

    Returns:
        Dictionary with scan results including status, keys added, and any errors
    """
    logger.info(f"Scanning SSH keys for host: {hostname}")

    known_hosts_path = "/root/.ssh/known_hosts"
    os.makedirs("/root/.ssh", mode=0o700, exist_ok=True)

    # Retry logic with exponential backoff
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            # Run ssh-keyscan
            scan_result = subprocess.run(
                ["ssh-keyscan", "-H", "-t", "rsa,ecdsa,ed25519", hostname],
                capture_output=True,
                text=True,
                timeout=timeout
            )

            if scan_result.returncode != 0:
                last_error = scan_result.stderr
                logger.warning(f"ssh-keyscan failed for {hostname} (attempt {attempt}/{retries}): {last_error}")

                if attempt < retries:
                    wait_time = 2 ** attempt  # Exponential backoff: 2, 4, 8 seconds
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                else:
                    return {
                        "host": hostname,
                        "status": "failed",
                        "error": last_error,
                        "message": f"Failed to scan SSH keys after {retries} attempts"
                    }

            # Parse the output
            if not scan_result.stdout.strip():
                last_error = "No keys returned from ssh-keyscan"
                logger.warning(f"No keys found for {hostname} (attempt {attempt}/{retries})")

                if attempt < retries:
                    wait_time = 2 ** attempt
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                else:
                    return {
                        "host": hostname,
                        "status": "failed",
                        "error": last_error,
                        "message": f"No SSH keys found after {retries} attempts"
                    }

            # Read existing known_hosts to check for duplicates
            existing_keys = set()
            if os.path.exists(known_hosts_path):
                with open(known_hosts_path, 'r') as f:
                    existing_keys = set(line.strip() for line in f if line.strip())

            # Parse new keys and filter out duplicates
            new_keys = []
            total_keys_scanned = 0
            for line in scan_result.stdout.splitlines():
                if line.strip():
                    total_keys_scanned += 1
                    if line.strip() not in existing_keys:
                        new_keys.append(line)

            # Add new keys to known_hosts
            if new_keys:
                with open(known_hosts_path, 'a') as f:
                    for key in new_keys:
                        f.write(key + '\n')
                os.chmod(known_hosts_path, 0o600)

            logger.info(f"Successfully scanned {hostname}: {len(new_keys)} new keys added, {total_keys_scanned} total keys scanned")

            return {
                "host": hostname,
                "status": "success",
                "keys_added": len(new_keys),
                "keys_scanned": total_keys_scanned,
                "message": f"Successfully added {len(new_keys)} new host keys"
            }

        except subprocess.TimeoutExpired:
            last_error = f"ssh-keyscan timed out after {timeout} seconds"
            logger.warning(f"Timeout scanning {hostname} (attempt {attempt}/{retries})")

            if attempt < retries:
                wait_time = 2 ** attempt
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                continue
            else:
                return {
                    "host": hostname,
                    "status": "failed",
                    "error": last_error,
                    "message": f"SSH key scan timed out after {retries} attempts"
                }

        except Exception as e:
            last_error = str(e)
            logger.error(f"Unexpected error scanning {hostname} (attempt {attempt}/{retries}): {e}", exc_info=True)

            if attempt < retries:
                wait_time = 2 ** attempt
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                continue
            else:
                return {
                    "host": hostname,
                    "status": "failed",
                    "error": last_error,
                    "message": f"Unexpected error after {retries} attempts"
                }

    # Should never reach here, but just in case
    return {
        "host": hostname,
        "status": "failed",
        "error": last_error or "Unknown error",
        "message": "Failed to scan SSH keys"
    }


def remove_host_keys(hostname: str) -> Dict[str, Any]:
    """
    Remove all known_hosts entries for a hostname using `ssh-keygen -R`.

    This is the mechanical step before `refresh_ssh_keys` re-scans and
    re-adds the current host key. It is a prerequisite for recovering
    from a `REMOTE HOST IDENTIFICATION HAS CHANGED` error, because SSH
    will refuse to connect as long as any stale entry remains.

    Args:
        hostname: The hostname whose known_hosts entries should be removed.

    Returns:
        Dict with keys: host, status ("success"|"not_present"|"failed"),
        and an optional error message.
    """
    known_hosts_path = "/root/.ssh/known_hosts"

    if not os.path.exists(known_hosts_path):
        return {
            "host": hostname,
            "status": "not_present",
            "message": "known_hosts file does not exist",
        }

    try:
        result = subprocess.run(
            ["ssh-keygen", "-f", known_hosts_path, "-R", hostname],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # ssh-keygen exits 0 whether it removed entries or not; the stdout
        # tells us if something was actually removed.
        if result.returncode != 0:
            logger.error(
                f"ssh-keygen -R failed for {hostname}: {result.stderr.strip()}"
            )
            return {
                "host": hostname,
                "status": "failed",
                "error": result.stderr.strip(),
            }

        removed = "not found" not in (result.stderr or "").lower() and "updated" in (
            result.stdout or ""
        ).lower()
        if removed:
            logger.info(f"Removed existing known_hosts entries for {hostname}")
            return {"host": hostname, "status": "success", "removed": True}

        return {"host": hostname, "status": "not_present", "removed": False}

    except subprocess.TimeoutExpired:
        return {
            "host": hostname,
            "status": "failed",
            "error": "ssh-keygen -R timed out",
        }
    except Exception as e:
        logger.error(f"Unexpected error removing host keys for {hostname}: {e}", exc_info=True)
        return {"host": hostname, "status": "failed", "error": str(e)}


def refresh_ssh_keys(hostname: str, timeout: int = 15, retries: int = 3) -> Dict[str, Any]:
    """
    Force-refresh SSH host keys: remove existing known_hosts entries for
    `hostname`, then rescan with `ssh-keyscan` and append the fresh keys.

    This is the recovery path for `REMOTE HOST IDENTIFICATION HAS CHANGED`
    errors, which occur whenever a remote host regenerates its SSH host
    keys — for example after a VM rebuild, an unclean shutdown that
    corrupts `/etc/ssh/ssh_host_*_key`, or a cloud-init first-boot.

    ⚠️  TAILSCALE-DEPENDENT SECURITY BOUNDARY ⚠️
    --------------------------------------------
    Blindly trusting a new host key is equivalent to trust-on-first-use
    (TOFU) re-applied on every reboot. It is only safe when the SSH
    transport is already authenticated by another layer — in this
    deployment, that layer is Tailscale / WireGuard.

    Tailscale guarantees peer identity via its own key exchange, so a
    rogue host cannot impersonate a known tailnet node even if the SSH
    host key changes. Without Tailscale, an attacker on the network path
    could feed us their own host key during the re-scan window and be
    silently trusted by the next `docker ps` call.

    If this provider is ever moved off of Tailscale, callers must stop
    calling this function and fall back to manual key management.

    Every successful refresh emits a WARNING-level log entry with the
    host name so that operators have an audit trail.

    Args:
        hostname: Hostname whose keys should be refreshed.
        timeout: Timeout passed through to `ssh-keyscan`.
        retries: Retry attempts passed through to `ssh-keyscan`.

    Returns:
        Dict with scan results from `scan_and_add_ssh_keys`, augmented
        with `removed_previous` indicating whether stale entries were
        cleared.
    """
    logger.warning(
        f"[SSH AUDIT] Refreshing host keys for '{hostname}'. "
        "Existing known_hosts entries will be DELETED and replaced with "
        "freshly-scanned keys. This action is only safe because SSH is "
        "tunneled over Tailscale — if you are reading this log on a "
        "non-Tailscale deployment, treat it as a potential MITM attack "
        "and investigate immediately."
    )

    remove_result = remove_host_keys(hostname)
    if remove_result["status"] == "failed":
        return {
            "host": hostname,
            "status": "failed",
            "error": f"Failed to remove old keys: {remove_result.get('error')}",
            "removed_previous": False,
        }

    scan_result = scan_and_add_ssh_keys(hostname, timeout=timeout, retries=retries)
    scan_result["removed_previous"] = remove_result.get("removed", False)

    if scan_result["status"] == "success":
        logger.warning(
            f"[SSH AUDIT] Host key refresh complete for '{hostname}' — "
            f"{scan_result.get('keys_added', 0)} new keys installed. "
            "If you did not expect a VM rebuild/reinstall for this host, "
            "audit it now."
        )

    return scan_result


def get_enabled_hosts_from_config(config_path: str = "/app/config/ssh-hosts.yaml") -> List[str]:
    """
    Parse ssh-hosts.yaml and return list of enabled hostnames

    Args:
        config_path: Path to the SSH hosts configuration file

    Returns:
        List of hostnames for enabled hosts
    """
    if not os.path.exists(config_path):
        logger.warning(f"SSH hosts config not found at {config_path}")
        return []

    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        if not config or 'hosts' not in config:
            logger.warning(f"No hosts configuration found in {config_path}")
            return []

        enabled_hosts = []
        for host_name, host_config in config['hosts'].items():
            if host_config.get('enabled', False):
                # Skip localhost (is_local=true) - no SSH keyscan needed
                if host_config.get('is_local', False):
                    logger.info(f"Skipping SSH keyscan for localhost: {host_name}")
                    continue

                # Use tailscale_hostname for SSH connections
                hostname = host_config.get('tailscale_hostname', host_name)
                enabled_hosts.append(hostname)

        logger.info(f"Found {len(enabled_hosts)} enabled hosts requiring SSH keyscan: {enabled_hosts}")
        return enabled_hosts

    except Exception as e:
        logger.error(f"Error parsing SSH hosts config: {e}", exc_info=True)
        return []


def initialize_ssh_known_hosts(config_path: str = "/app/config/ssh-hosts.yaml") -> Dict[str, Any]:
    """
    Initialize SSH known_hosts by scanning all enabled hosts from configuration

    This function should be called once during application startup.

    Args:
        config_path: Path to the SSH hosts configuration file

    Returns:
        Dictionary with initialization results including success/failure counts
    """
    logger.info("Initializing SSH known_hosts for Tailscale hosts")

    # Ensure .ssh directory exists with correct permissions
    os.makedirs("/root/.ssh", mode=0o700, exist_ok=True)
    known_hosts_path = "/root/.ssh/known_hosts"

    # Create known_hosts if it doesn't exist
    if not os.path.exists(known_hosts_path):
        open(known_hosts_path, 'a').close()
        os.chmod(known_hosts_path, 0o600)

    # Get enabled hosts from configuration
    hostnames = get_enabled_hosts_from_config(config_path)

    if not hostnames:
        logger.warning("No enabled hosts found in configuration, skipping SSH key scanning")
        return {
            "status": "skipped",
            "message": "No enabled hosts configured",
            "hosts_scanned": 0,
            "hosts_succeeded": 0,
            "hosts_failed": 0,
            "results": []
        }

    # Scan each host
    results = []
    succeeded = 0
    failed = 0

    for hostname in hostnames:
        result = scan_and_add_ssh_keys(hostname, timeout=15, retries=3)
        results.append(result)

        if result["status"] == "success":
            succeeded += 1
        else:
            failed += 1

    # Summary
    total_keys_added = sum(r.get("keys_added", 0) for r in results)
    logger.info(f"SSH known_hosts initialization complete: {succeeded} succeeded, {failed} failed, {total_keys_added} keys added")

    if failed > 0:
        failed_hosts = [r["host"] for r in results if r["status"] == "failed"]
        logger.warning(f"Failed to scan keys for: {', '.join(failed_hosts)}")
        logger.info("These hosts can be manually added later using: POST /api/ssh/scan-keys/<hostname>")

    return {
        "status": "completed",
        "message": f"Scanned {len(hostnames)} hosts: {succeeded} succeeded, {failed} failed",
        "hosts_scanned": len(hostnames),
        "hosts_succeeded": succeeded,
        "hosts_failed": failed,
        "total_keys_added": total_keys_added,
        "results": results
    }
