"""
SSH setup utilities for Tailscale SSH authentication
Handles SSH known_hosts population for remote Docker hosts
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

                hostname = host_config.get('hostname', host_name)
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
