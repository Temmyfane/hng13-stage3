#!/usr/bin/env python3
"""
Error handling and recovery system for robust log watcher
"""

import time
import traceback
from typing import Dict, Optional
from watcher_models import ErrorContext, RecoveryAction, CircuitBreakerState, StateManager


class ErrorHandler:
    """Comprehensive error recovery and circuit breaker implementation"""
    
    def __init__(self, state_manager: StateManager):
        self.state_manager = state_manager
        self.error_contexts: Dict[str, ErrorContext] = {}
        
        # Configurable retry settings
        self.max_retries = {
            'file_operation': 5,
            'stream_error': 3,
            'permission_error': 10,
            'network_error': 3
        }
        
        self.base_backoff = 1.0  # Base backoff in seconds
        self.max_backoff = 30.0  # Maximum backoff in seconds
        
        # Circuit breaker settings
        self.cb_failure_threshold = 5
        self.cb_timeout = 60.0  # seconds
        self.cb_half_open_max_calls = 3
    
    def classify_error(self, error: Exception) -> str:
        """Classify error type for appropriate handling"""
        error_msg = str(error).lower()
        
        if "underlying stream is not seekable" in error_msg:
            return "stream_error"
        elif "permission denied" in error_msg or "access denied" in error_msg:
            return "permission_error"
        elif "no such file" in error_msg or "file not found" in error_msg:
            return "file_not_found"
        elif "connection" in error_msg or "network" in error_msg:
            return "network_error"
        elif "disk" in error_msg or "space" in error_msg:
            return "disk_error"
        else:
            return "unknown_error"
    
    def handle_error(self, error: Exception, component: str) -> RecoveryAction:
        """Main error handling logic with recovery action determination"""
        error_type = self.classify_error(error)
        context_key = f"{component}_{error_type}"
        
        # Get or create error context
        if context_key not in self.error_contexts:
            self.error_contexts[context_key] = ErrorContext(
                error_type=error_type,
                component=component,
                attempt_count=0,
                last_attempt_time=0,
                error_message=str(error),
                stack_trace=traceback.format_exc()
            )
        
        context = self.error_contexts[context_key]
        context.attempt_count += 1
        context.last_attempt_time = time.time()
        context.error_message = str(error)
        
        print(f"🚨 Error in {component}: {error_type} (attempt {context.attempt_count})")
        print(f"   Message: {str(error)}")
        
        # Check circuit breaker
        cb_state = self.state_manager.get_circuit_breaker(component)
        if self._should_circuit_break(cb_state, context):
            return RecoveryAction.CIRCUIT_BREAKER
        
        # Determine recovery action based on error type and attempt count
        return self._get_recovery_action(error_type, context)
    
    def _get_recovery_action(self, error_type: str, context: ErrorContext) -> RecoveryAction:
        """Determine appropriate recovery action"""
        max_attempts = self.max_retries.get(error_type, 3)
        
        if context.attempt_count > max_attempts:
            if error_type in ['stream_error', 'file_not_found']:
                return RecoveryAction.RESTART_COMPONENT
            else:
                return RecoveryAction.FATAL_EXIT
        
        # Special handling for stream errors (the main issue we're solving)
        if error_type == "stream_error":
            if context.attempt_count == 1:
                return RecoveryAction.RETRY_IMMEDIATE  # First attempt - quick retry
            else:
                return RecoveryAction.RETRY_WITH_BACKOFF
        
        # Transient errors - retry immediately
        if error_type in ['file_not_found', 'permission_error']:
            return RecoveryAction.RETRY_WITH_BACKOFF
        
        # Network errors
        if error_type == 'network_error':
            return RecoveryAction.RETRY_WITH_BACKOFF
        
        # Unknown errors - be cautious
        return RecoveryAction.RETRY_WITH_BACKOFF
    
    def should_retry(self, error_type: str, attempt_count: int) -> bool:
        """Check if we should retry based on error type and attempt count"""
        max_attempts = self.max_retries.get(error_type, 3)
        return attempt_count <= max_attempts
    
    def get_backoff_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay"""
        delay = self.base_backoff * (2 ** (attempt - 1))
        return min(delay, self.max_backoff)
    
    def _should_circuit_break(self, cb_state: CircuitBreakerState, context: ErrorContext) -> bool:
        """Check if circuit breaker should open"""
        now = time.time()
        
        # If circuit is already open, check if we should try again
        if cb_state.is_open:
            if now >= cb_state.next_attempt_time:
                # Try half-open state
                cb_state.is_open = False
                print(f"🔄 Circuit breaker half-open for {context.component}")
                return False
            else:
                return True
        
        # Check if we should open the circuit
        if context.attempt_count >= self.cb_failure_threshold:
            recent_failures = self._count_recent_failures(context, now)
            if recent_failures >= self.cb_failure_threshold:
                cb_state.is_open = True
                cb_state.failure_count = recent_failures
                cb_state.last_failure_time = now
                cb_state.next_attempt_time = now + self.cb_timeout
                
                self.state_manager.update_circuit_breaker(context.component, cb_state)
                print(f"⚡ Circuit breaker opened for {context.component}")
                return True
        
        return False
    
    def _count_recent_failures(self, context: ErrorContext, now: float) -> int:
        """Count failures in recent time window"""
        # For simplicity, using attempt count as proxy for recent failures
        # In a more sophisticated implementation, we'd track failure timestamps
        return context.attempt_count
    
    def record_success(self, component: str):
        """Record successful operation for circuit breaker"""
        cb_state = self.state_manager.get_circuit_breaker(component)
        if cb_state.is_open:
            cb_state.is_open = False
            cb_state.failure_count = 0
            cb_state.last_success_time = time.time()
            self.state_manager.update_circuit_breaker(component, cb_state)
            print(f"✅ Circuit breaker closed for {component}")
        
        # Reset error context on success
        for key in list(self.error_contexts.keys()):
            if key.startswith(component):
                del self.error_contexts[key]
    
    def trigger_circuit_breaker(self, component: str):
        """Manually trigger circuit breaker"""
        cb_state = self.state_manager.get_circuit_breaker(component)
        cb_state.is_open = True
        cb_state.next_attempt_time = time.time() + self.cb_timeout
        self.state_manager.update_circuit_breaker(component, cb_state)
        print(f"🔴 Circuit breaker manually triggered for {component}")
    
    def is_circuit_open(self, component: str) -> bool:
        """Check if circuit breaker is open for component"""
        cb_state = self.state_manager.get_circuit_breaker(component)
        if cb_state.is_open and time.time() >= cb_state.next_attempt_time:
            # Time to try half-open
            return False
        return cb_state.is_open