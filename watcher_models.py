#!/usr/bin/env python3
"""
Data models and state management for robust log watcher
"""

import json
import os
import time
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Dict, List, Optional, Any
from collections import deque


class RecoveryAction(Enum):
    """Actions to take when recovering from errors"""
    RETRY_IMMEDIATE = "retry_immediate"
    RETRY_WITH_BACKOFF = "retry_with_backoff"
    RESTART_COMPONENT = "restart_component"
    CIRCUIT_BREAKER = "circuit_breaker"
    FATAL_EXIT = "fatal_exit"


@dataclass
class ErrorContext:
    """Context information for error handling"""
    error_type: str
    component: str
    attempt_count: int
    last_attempt_time: float
    error_message: str
    stack_trace: Optional[str] = None


@dataclass
class CircuitBreakerState:
    """State of a circuit breaker"""
    is_open: bool = False
    failure_count: int = 0
    last_failure_time: float = 0
    last_success_time: float = 0
    next_attempt_time: float = 0


@dataclass
class WatcherState:
    """Persistent state for the log watcher"""
    current_pool: Optional[str] = None
    last_alert_times: Dict[str, float] = None
    error_rate_window: List[Dict[str, Any]] = None
    file_position: int = 0
    file_inode: Optional[int] = None
    circuit_breaker_states: Dict[str, CircuitBreakerState] = None
    last_health_check: float = 0
    startup_time: float = 0
    
    def __post_init__(self):
        if self.last_alert_times is None:
            self.last_alert_times = {}
        if self.error_rate_window is None:
            self.error_rate_window = []
        if self.circuit_breaker_states is None:
            self.circuit_breaker_states = {}
        if self.startup_time == 0:
            self.startup_time = time.time()


class StateManager:
    """Manages persistent state across watcher restarts"""
    
    def __init__(self, state_path: str = "/tmp/watcher_state.json"):
        self.state_path = state_path
        self.backup_path = f"{state_path}.backup"
        self.state = WatcherState()
        self.load_state()
    
    def save_state(self) -> bool:
        """Save state with atomic write and backup"""
        try:
            # Create backup of current state file
            if os.path.exists(self.state_path):
                with open(self.state_path, 'r') as src, open(self.backup_path, 'w') as dst:
                    dst.write(src.read())
            
            # Convert circuit breaker states to dict for JSON serialization
            state_dict = asdict(self.state)
            cb_states = {}
            for name, cb_state in self.state.circuit_breaker_states.items():
                cb_states[name] = asdict(cb_state)
            state_dict['circuit_breaker_states'] = cb_states
            
            # Atomic write using temp file
            temp_path = f"{self.state_path}.tmp"
            with open(temp_path, 'w') as f:
                json.dump(state_dict, f, indent=2)
            
            # Atomic move
            os.rename(temp_path, self.state_path)
            return True
            
        except Exception as e:
            print(f"❌ Failed to save state: {e}")
            return False
    
    def load_state(self) -> bool:
        """Load state with fallback to backup and defaults"""
        for path in [self.state_path, self.backup_path]:
            if not os.path.exists(path):
                continue
                
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                
                # Convert circuit breaker states back from dict
                cb_states = {}
                for name, cb_data in data.get('circuit_breaker_states', {}).items():
                    cb_states[name] = CircuitBreakerState(**cb_data)
                data['circuit_breaker_states'] = cb_states
                
                self.state = WatcherState(**data)
                print(f"✅ Loaded state from {path}")
                return True
                
            except Exception as e:
                print(f"⚠️  Failed to load state from {path}: {e}")
                continue
        
        print("📝 Using default state (no saved state found)")
        return False
    
    def update_pool_state(self, pool: str):
        """Update current pool and save state"""
        if self.state.current_pool != pool:
            print(f"🔄 Pool state change: {self.state.current_pool} → {pool}")
            self.state.current_pool = pool
            self.save_state()
    
    def get_alert_cooldown(self, alert_type: str) -> float:
        """Get time remaining for alert cooldown"""
        last_time = self.state.last_alert_times.get(alert_type, 0)
        return max(0, last_time - time.time())
    
    def set_alert_time(self, alert_type: str, alert_time: float = None):
        """Set last alert time for cooldown tracking"""
        if alert_time is None:
            alert_time = time.time()
        self.state.last_alert_times[alert_type] = alert_time
        self.save_state()
    
    def add_request_to_window(self, request_data: Dict[str, Any]):
        """Add request to error rate window"""
        self.state.error_rate_window.append(request_data)
        
        # Keep only recent requests (sliding window)
        window_size = int(os.getenv('WINDOW_SIZE', '200'))
        if len(self.state.error_rate_window) > window_size:
            self.state.error_rate_window = self.state.error_rate_window[-window_size:]
        
        # Save state periodically (every 10 requests to avoid too much I/O)
        if len(self.state.error_rate_window) % 10 == 0:
            self.save_state()
    
    def get_error_rate(self) -> float:
        """Calculate current error rate from window"""
        if not self.state.error_rate_window:
            return 0.0
        
        error_count = sum(1 for req in self.state.error_rate_window 
                         if req.get('is_error', False))
        return (error_count / len(self.state.error_rate_window)) * 100
    
    def update_file_position(self, position: int, inode: Optional[int] = None):
        """Update file position for resume after restart"""
        self.state.file_position = position
        if inode is not None:
            self.state.file_inode = inode
        # Don't save on every position update - too expensive
    
    def get_circuit_breaker(self, component: str) -> CircuitBreakerState:
        """Get circuit breaker state for component"""
        if component not in self.state.circuit_breaker_states:
            self.state.circuit_breaker_states[component] = CircuitBreakerState()
        return self.state.circuit_breaker_states[component]
    
    def update_circuit_breaker(self, component: str, cb_state: CircuitBreakerState):
        """Update circuit breaker state"""
        self.state.circuit_breaker_states[component] = cb_state
        self.save_state()