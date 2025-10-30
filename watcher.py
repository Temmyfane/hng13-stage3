#!/usr/bin/env python3
"""
Nginx Log Watcher - Monitors logs and sends Slack alerts with stream error recovery
"""

import os
import json
import time
import requests
from collections import deque
from datetime import datetime

# Environment variables
SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL', '')
ERROR_RATE_THRESHOLD = float(os.getenv('ERROR_RATE_THRESHOLD', '2.0'))  # percentage
WINDOW_SIZE = int(os.getenv('WINDOW_SIZE', '200'))  # requests
ALERT_COOLDOWN_SEC = int(os.getenv('ALERT_COOLDOWN_SEC', '300'))  # 5 minutes
MAINTENANCE_MODE = os.getenv('MAINTENANCE_MODE', 'false').lower() == 'true'

# State tracking
last_pool = None
request_window = deque(maxlen=WINDOW_SIZE)
last_alert_time = {}

def send_slack_alert(message, alert_type='info'):
    """Send alert to Slack with cooldown"""
    if MAINTENANCE_MODE:
        print(f"🔇 MAINTENANCE MODE: Suppressing alert - {message}")
        return
    
    if not SLACK_WEBHOOK_URL:
        print(f"⚠️  No Slack webhook configured: {message}")
        return
    
    # Check cooldown
    now = time.time()
    if alert_type in last_alert_time:
        time_since_last = now - last_alert_time[alert_type]
        if time_since_last < ALERT_COOLDOWN_SEC:
            print(f"🔕 Alert suppressed (cooldown): {message}")
            return
    
    # Icon based on alert type
    icons = {
        'failover': '🔄',
        'error_rate': '🚨',
        'recovery': '✅',
        'info': 'ℹ️'
    }
    icon = icons.get(alert_type, 'ℹ️')
    
    payload = {
        "text": f"{icon} *Backend.im Alert*",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{icon} Backend.im Monitoring Alert"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": message
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | *Type:* {alert_type}"
                    }
                ]
            }
        ]
    }
    
    try:
        response = requests.post(
            SLACK_WEBHOOK_URL,
            json=payload,
            timeout=10
        )
        if response.status_code == 200:
            print(f"✅ Slack alert sent: {message[:50]}...")
            last_alert_time[alert_type] = now
        else:
            print(f"❌ Slack alert failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Error sending Slack alert: {e}")

def parse_log_line(line):
    """Parse JSON log line from Nginx"""
    try:
        data = json.loads(line)
        return {
            'pool': data.get('pool', 'unknown'),
            'status': int(data.get('status', 0)),
            'upstream_status': data.get('upstream_status', ''),
            'upstream_addr': data.get('upstream_addr', ''),
            'request_time': float(data.get('request_time', 0)),
            'request': data.get('request', ''),
            'release': data.get('release', 'unknown')
        }
    except json.JSONDecodeError:
        return None
    except (ValueError, TypeError):
        return None

def check_failover(current_pool):
    """Detect pool failover"""
    global last_pool
    
    if last_pool is None:
        last_pool = current_pool
        print(f"📍 Initial pool: {current_pool}")
        return
    
    if current_pool != last_pool and current_pool != 'unknown':
        message = (
            f"*🔄 Failover Detected*\n\n"
            f"Pool switched: `{last_pool}` → `{current_pool}`\n"
            f"*Action Required:* Check health of `{last_pool}` container\n"
            f"```\n"
            f"docker-compose logs app_{last_pool}\n"
            f"curl http://localhost:808{'1' if last_pool == 'blue' else '2'}/healthz\n"
            f"```"
        )
        send_slack_alert(message, 'failover')
        print(f"🔄 FAILOVER: {last_pool} → {current_pool}")
        last_pool = current_pool

def check_error_rate():
    """Calculate error rate over sliding window"""
    if len(request_window) < WINDOW_SIZE:
        return  # Not enough data yet
    
    error_count = sum(1 for req in request_window if req.get('is_error', False))
    error_rate = (error_count / len(request_window)) * 100
    
    if error_rate > ERROR_RATE_THRESHOLD:
        message = (
            f"*🚨 High Error Rate Detected*\n\n"
            f"Error rate: `{error_rate:.2f}%` (threshold: {ERROR_RATE_THRESHOLD}%)\n"
            f"Window: last {WINDOW_SIZE} requests\n"
            f"Errors: {error_count}/{len(request_window)} requests\n\n"
            f"*Action Required:*\n"
            f"• Check upstream logs: `docker-compose logs app_blue app_green`\n"
            f"• Consider manual pool toggle if needed\n"
            f"• Verify external dependencies"
        )
        send_slack_alert(message, 'error_rate')
        print(f"🚨 ERROR RATE: {error_rate:.2f}% ({error_count}/{len(request_window)})")

def tail_log_file_robust(log_path):
    """Tail nginx log file with stream error recovery"""
    print(f"👀 Watching log file: {log_path}")
    print(f"📊 Window size: {WINDOW_SIZE} requests")
    print(f"⚠️  Error threshold: {ERROR_RATE_THRESHOLD}%")
    print(f"⏱️  Alert cooldown: {ALERT_COOLDOWN_SEC}s")
    print(f"🔇 Maintenance mode: {MAINTENANCE_MODE}")
    print("-" * 50)
    
    retry_count = 0
    max_retries = 5
    
    while retry_count < max_retries:
        try:
            # Wait for log file to exist
            while not os.path.exists(log_path):
                print(f"⏳ Waiting for log file: {log_path}")
                time.sleep(2)
            
            # Open and seek to end
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                # Go to end of file
                f.seek(0, 2)
                retry_count = 0  # Reset retry count on successful open
                
                while True:
                    try:
                        line = f.readline()
                        if not line:
                            time.sleep(0.1)
                            continue
                        
                        # Parse log line
                        log_data = parse_log_line(line.strip())
                        if not log_data:
                            continue
                        
                        # Track request in window
                        is_error = log_data['status'] >= 500
                        request_window.append({
                            'pool': log_data['pool'],
                            'is_error': is_error,
                            'timestamp': time.time()
                        })
                        
                        # Check for failover
                        if log_data['pool'] != 'unknown':
                            check_failover(log_data['pool'])
                        
                        # Check error rate
                        check_error_rate()
                        
                        # Log interesting events
                        if is_error:
                            print(f"❌ Error: {log_data['status']} | Pool: {log_data['pool']} | {log_data['request']}")
                        elif log_data['pool'] != 'unknown':
                            print(f"✓ {log_data['pool']} | {log_data['status']} | {log_data['request']}")
                    
                    except (OSError, IOError) as e:
                        if "underlying stream is not seekable" in str(e):
                            print("🔧 Stream error detected - reopening file")
                            break  # Break inner loop to reopen file
                        else:
                            raise  # Re-raise other IO errors
                            
        except Exception as e:
            retry_count += 1
            print(f"💥 Error (attempt {retry_count}/{max_retries}): {e}")
            
            if retry_count >= max_retries:
                print("❌ Max retries exceeded")
                send_slack_alert(f"*💥 Watcher Crashed*\n\n```{str(e)}```", 'error_rate')
                raise
            
            # Exponential backoff
            backoff = min(2 ** retry_count, 30)
            print(f"⏳ Retrying in {backoff}s...")
            time.sleep(backoff)

def main():
    """Main entry point"""
    log_path = '/var/log/nginx/access.log'
    
    print("=" * 50)
    print("🚀 Backend.im Log Watcher Starting (Stream Error Fixed)")
    print("=" * 50)
    
    # Send startup notification
    send_slack_alert(
        "*🚀 Log Watcher Started*\n\nMonitoring nginx logs with stream error recovery.",
        'info'
    )
    
    try:
        tail_log_file_robust(log_path)
    except KeyboardInterrupt:
        print("\n⏹️  Log watcher stopped")
    except Exception as e:
        print(f"💥 Fatal error: {e}")
        send_slack_alert(f"*💥 Watcher Crashed*\n\n```{str(e)}```", 'error_rate')

if __name__ == '__main__':
    main()