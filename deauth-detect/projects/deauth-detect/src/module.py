#!/usr/bin/env python3
"""
NullSec DeauthDetect - WiFi Deauthentication Attack Detector
Monitors for deauth/disassoc frames and alerts on potential attacks.
For WiFi Pineapple MK7 / Enterprise.
"""

from typing import Optional, List, Dict
from datetime import datetime
from logging import Logger
import logging
import pathlib
import subprocess
import os
import json
import signal
import re

from pineapple.modules import Module, Request
from pineapple.jobs import Job, JobManager
from pineapple.helpers.opkg_helpers import OpkgJob
import pineapple.helpers.notification_helpers as notifier

module = Module('deauth-detect', logging.DEBUG)
job_manager = JobManager(name='deauth-detect', module=module, log_level=logging.DEBUG)

MONITOR_DIR_PATH = '/root/.deauth-detect'
MONITOR_DIR = pathlib.Path(MONITOR_DIR_PATH)
ALERTS_FILE = f'{MONITOR_DIR_PATH}/alerts.json'
STATS_FILE = f'{MONITOR_DIR_PATH}/stats.json'


class DeauthMonitorJob(Job[bool]):
    """Background job that monitors for deauthentication frames using tcpdump."""

    def __init__(self, interface: str, threshold: int = 10, window: int = 30,
                 webhook_url: str = '', channel_hop: bool = True):
        super().__init__()
        self.interface = interface
        self.threshold = threshold  # deauth frames per window to trigger alert
        self.window = window  # time window in seconds
        self.webhook_url = webhook_url
        self.channel_hop = channel_hop
        self.proc = None
        self.hop_proc = None
        self.deauth_count = 0
        self.total_deauths = 0
        self.alerts = []
        self.attackers = {}  # MAC -> count mapping

    def do_work(self, logger: Logger) -> bool:
        logger.debug(f'Starting deauth monitor on {self.interface}')

        # Ensure monitor interface is up
        try:
            subprocess.run(['ifconfig', self.interface, 'up'], capture_output=True)
        except Exception as e:
            logger.error(f'Failed to bring up interface: {e}')
            return False

        # Start channel hopping if enabled
        if self.channel_hop:
            self._start_channel_hop(logger)

        # Use tcpdump to capture deauth/disassoc frames
        # Type 0 subtype 12 = deauth, subtype 10 = disassoc
        cmd = [
            'tcpdump', '-i', self.interface, '-l', '-e',
            'type mgt subtype deauth or type mgt subtype disassoc',
            '-c', '0'  # unlimited capture
        ]

        logger.debug(f'Running: {" ".join(cmd)}')

        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, bufsize=1
            )
        except FileNotFoundError:
            logger.error('tcpdump not found. Install with: opkg install tcpdump')
            return False

        window_start = datetime.now()
        window_count = 0

        for line in iter(self.proc.stdout.readline, ''):
            if not line:
                continue

            self.total_deauths += 1
            window_count += 1

            # Parse the deauth frame
            parsed = self._parse_deauth_frame(line.strip())
            if parsed:
                src_mac = parsed.get('src', 'unknown')
                dst_mac = parsed.get('dst', 'unknown')
                self.attackers[src_mac] = self.attackers.get(src_mac, 0) + 1

                logger.debug(f'Deauth: {src_mac} -> {dst_mac} (window: {window_count})')

            # Check if we've exceeded threshold within window
            elapsed = (datetime.now() - window_start).total_seconds()
            if elapsed >= self.window:
                if window_count >= self.threshold:
                    alert = self._create_alert(window_count, elapsed)
                    self.alerts.append(alert)
                    self._save_alerts()
                    self._send_webhook(alert, logger)

                    logger.warning(
                        f'DEAUTH ATTACK DETECTED: {window_count} frames in {elapsed:.0f}s'
                    )

                # Reset window
                window_start = datetime.now()
                window_count = 0

                # Save stats periodically
                self._save_stats()

        return True

    def _parse_deauth_frame(self, line: str) -> Optional[Dict]:
        """Parse a tcpdump deauth frame line."""
        result = {}
        # Extract MAC addresses from tcpdump output
        # Format varies, but typically: SA:xx:xx:xx:xx:xx:xx DA:yy:yy:yy:yy:yy:yy
        mac_pattern = r'([0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2})'
        macs = re.findall(mac_pattern, line)
        if len(macs) >= 2:
            result['src'] = macs[0]
            result['dst'] = macs[1]
        elif len(macs) == 1:
            result['src'] = macs[0]
            result['dst'] = 'broadcast'

        # Check for reason code
        reason_match = re.search(r'Reason:\s*(\d+)', line, re.IGNORECASE)
        if reason_match:
            result['reason'] = int(reason_match.group(1))

        if 'Deauthentication' in line or 'deauth' in line.lower():
            result['type'] = 'deauth'
        else:
            result['type'] = 'disassoc'

        return result if result else None

    def _create_alert(self, count: int, elapsed: float) -> Dict:
        """Create an alert record."""
        # Find top attackers in current window
        top_attackers = sorted(
            self.attackers.items(), key=lambda x: x[1], reverse=True
        )[:5]

        return {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'deauth_count': count,
            'window_seconds': round(elapsed, 1),
            'rate': round(count / max(elapsed, 1), 1),
            'total_deauths': self.total_deauths,
            'top_attackers': [
                {'mac': mac, 'count': cnt} for mac, cnt in top_attackers
            ],
            'severity': self._calc_severity(count, elapsed)
        }

    def _calc_severity(self, count: int, elapsed: float) -> str:
        """Calculate alert severity based on deauth rate."""
        rate = count / max(elapsed, 1)
        if rate > 10:
            return 'CRITICAL'
        elif rate > 5:
            return 'HIGH'
        elif rate > 2:
            return 'MEDIUM'
        return 'LOW'

    def _save_alerts(self):
        """Persist alerts to disk."""
        try:
            with open(ALERTS_FILE, 'w') as f:
                json.dump(self.alerts[-100:], f, indent=2)  # Keep last 100 alerts
        except Exception:
            pass

    def _save_stats(self):
        """Save current statistics."""
        try:
            stats = {
                'total_deauths': self.total_deauths,
                'alert_count': len(self.alerts),
                'unique_attackers': len(self.attackers),
                'top_attackers': sorted(
                    [{'mac': m, 'count': c} for m, c in self.attackers.items()],
                    key=lambda x: x['count'], reverse=True
                )[:20],
                'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'monitoring_interface': self.interface
            }
            with open(STATS_FILE, 'w') as f:
                json.dump(stats, f, indent=2)
        except Exception:
            pass

    def _send_webhook(self, alert: Dict, logger: Logger):
        """Send alert to webhook (Discord/Slack)."""
        if not self.webhook_url:
            return

        try:
            severity = alert['severity']
            emoji = {'CRITICAL': '🚨', 'HIGH': '⚠️', 'MEDIUM': '🔶', 'LOW': 'ℹ️'}.get(severity, '❓')

            msg = (
                f"{emoji} **Deauth Attack Detected** [{severity}]\n"
                f"• **{alert['deauth_count']}** deauth frames in {alert['window_seconds']}s "
                f"({alert['rate']} frames/sec)\n"
                f"• Total deauths: {alert['total_deauths']}\n"
                f"• Top attacker: {alert['top_attackers'][0]['mac'] if alert['top_attackers'] else 'unknown'}"
            )

            import urllib.request
            data = json.dumps({'content': msg}).encode()
            req = urllib.request.Request(
                self.webhook_url, data=data,
                headers={'Content-Type': 'application/json'}
            )
            urllib.request.urlopen(req, timeout=5)
            logger.debug('Webhook notification sent')
        except Exception as e:
            logger.error(f'Webhook failed: {e}')

    def _start_channel_hop(self, logger: Logger):
        """Start channel hopping on the monitor interface."""
        hop_script = (
            f'while true; do '
            f'for ch in 1 2 3 4 5 6 7 8 9 10 11 12 13; do '
            f'iwconfig {self.interface} channel $ch 2>/dev/null; '
            f'sleep 0.3; '
            f'done; done'
        )
        try:
            self.hop_proc = subprocess.Popen(
                ['sh', '-c', hop_script],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            logger.debug('Channel hopping started')
        except Exception as e:
            logger.error(f'Failed to start channel hopping: {e}')

    def stop(self):
        """Stop monitoring."""
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

        if self.hop_proc:
            self.hop_proc.terminate()
            try:
                self.hop_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.hop_proc.kill()

        os.system('killall -9 tcpdump 2>/dev/null')
        self._save_stats()
        self._save_alerts()


def _notify_monitor_complete(job: DeauthMonitorJob):
    if not job.was_successful:
        module.send_notification(f'Monitor error: {job.error}', notifier.ERROR)
    else:
        module.send_notification('Deauth monitoring stopped', notifier.INFO)


def _notify_dependencies_finished(job: OpkgJob):
    if not job.was_successful:
        module.send_notification(job.error, notifier.ERROR)
    elif job.install:
        module.send_notification('Dependencies installed successfully.', notifier.INFO)


@module.on_start()
def init():
    """Initialize module directories."""
    if not MONITOR_DIR.exists():
        MONITOR_DIR.mkdir(parents=True)


@module.on_shutdown()
def shutdown(signal_num: int = None):
    """Stop all monitoring on module shutdown."""
    for job_runner in job_manager.jobs.values():
        if job_runner.running and isinstance(job_runner.job, DeauthMonitorJob):
            job_runner.job.stop()


@module.handles_action('check_dependencies')
def check_dependencies(request: Request):
    """Check if tcpdump is installed."""
    from pineapple.helpers import opkg_helpers as opkg
    return opkg.check_if_installed('tcpdump', module.logger)


@module.handles_action('manage_dependencies')
def manage_dependencies(request: Request):
    """Install/remove tcpdump dependency."""
    return {
        'job_id': job_manager.execute_job(
            OpkgJob('tcpdump', request.install),
            callbacks=[_notify_dependencies_finished]
        )
    }


@module.handles_action('get_interfaces')
def get_interfaces(request: Request):
    """Get available wireless interfaces."""
    try:
        result = subprocess.run(
            ['iwconfig'], capture_output=True, text=True, stderr=subprocess.STDOUT
        )
        interfaces = []
        current = None
        for line in result.stdout.split('\n'):
            if not line.startswith(' ') and line.strip():
                iface = line.split()[0]
                if 'no wireless extensions' not in line:
                    current = {'name': iface, 'mode': 'unknown'}
                    interfaces.append(current)
            elif current and 'Mode:' in line:
                mode_match = re.search(r'Mode:(\S+)', line)
                if mode_match:
                    current['mode'] = mode_match.group(1)

        return interfaces
    except Exception as e:
        return {'error': str(e)}


@module.handles_action('start_monitor')
def start_monitor(request: Request):
    """Start deauth detection monitoring."""
    interface = getattr(request, 'interface', 'wlan1mon')
    threshold = getattr(request, 'threshold', 10)
    window = getattr(request, 'window', 30)
    webhook = getattr(request, 'webhook', '')
    channel_hop = getattr(request, 'channel_hop', True)

    # Check if already monitoring
    for job_id, job_runner in job_manager.jobs.items():
        if job_runner.running and isinstance(job_runner.job, DeauthMonitorJob):
            return {'error': 'Monitor already running', 'job_id': job_id}

    job = DeauthMonitorJob(
        interface=interface,
        threshold=int(threshold),
        window=int(window),
        webhook_url=webhook,
        channel_hop=channel_hop
    )

    job_id = job_manager.execute_job(job, callbacks=[_notify_monitor_complete])
    module.send_notification(
        f'Deauth monitoring started on {interface}', notifier.INFO
    )

    return {'job_id': job_id}


@module.handles_action('stop_monitor')
def stop_monitor(request: Request):
    """Stop deauth detection monitoring."""
    shutdown()
    return True


@module.handles_action('get_status')
def get_status(request: Request):
    """Get current monitoring status."""
    running = False
    job_id = None

    for jid, job_runner in job_manager.jobs.items():
        if job_runner.running and isinstance(job_runner.job, DeauthMonitorJob):
            running = True
            job_id = jid
            break

    stats = {}
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, 'r') as f:
                stats = json.load(f)
        except Exception:
            pass

    return {
        'running': running,
        'job_id': job_id,
        'stats': stats
    }


@module.handles_action('get_alerts')
def get_alerts(request: Request):
    """Get recorded alerts."""
    if os.path.exists(ALERTS_FILE):
        try:
            with open(ALERTS_FILE, 'r') as f:
                alerts = json.load(f)
            return alerts
        except Exception:
            return []
    return []


@module.handles_action('clear_alerts')
def clear_alerts(request: Request):
    """Clear all recorded alerts."""
    if os.path.exists(ALERTS_FILE):
        os.remove(ALERTS_FILE)
    if os.path.exists(STATS_FILE):
        os.remove(STATS_FILE)
    return True


@module.handles_action('get_stats')
def get_stats(request: Request):
    """Get monitoring statistics."""
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {
        'total_deauths': 0,
        'alert_count': 0,
        'unique_attackers': 0,
        'top_attackers': [],
        'monitoring_interface': 'N/A'
    }


@module.handles_action('rebind_last_job')
def rebind_last_job(request: Request):
    """Reconnect to last background job."""
    last_job_id = None
    last_job_type = None

    if len(job_manager.jobs) >= 1:
        last_job_id = list(job_manager.jobs.keys())[-1]
        if isinstance(job_manager.jobs[last_job_id].job, DeauthMonitorJob):
            last_job_type = 'monitor'
        elif isinstance(job_manager.jobs[last_job_id].job, OpkgJob):
            last_job_type = 'opkg'
        else:
            last_job_type = 'unknown'

    return {'job_id': last_job_id, 'job_type': last_job_type}


if __name__ == '__main__':
    module.start()
