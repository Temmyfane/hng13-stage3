#!/usr/bin/env python3
"""
Robust file management system for log watching with rotation detection
"""

import os
import time
import stat
from typing import Iterator, Optional, TextIO
from watcher_models import StateManager, RecoveryAction
from error_handler import ErrorHandler


class LogFileManager:
    """Robust file handling with rotation detection and stream recovery"""
    
    def __init__(self, state_manager: StateManager, error_handler: ErrorHandler):
        self.state_manager = state_manager
        self.error_handler = error_handler
        self.current_file: Optional[TextIO] = None
        self.current_path: Optional[str] = None
        self.current_inode: Optional[int] = None
        self.last_position: int = 0
        
    def watch_file(self, path: str) -> Iterator[str]:
        """Main file watching with automatic recovery"""
        self.current_path = path
        print(f"👀 Starting to watch: {path}")
        
        while True:
            try:
                # Ensure file is open and ready
                if not self._ensure_file_open():
                    time.sleep(1)
                    continue
                
                # Read available lines
                lines_read = 0
                for line in self._read_lines():
                    yield line
                    lines_read += 1
                
                # Check for rotation if we read some lines
                if lines_read > 0:
                    if self.detect_rotation():
                        print("🔄 Log rotation detected, reopening file")
                        self._close_file()
                        continue
                
                # No new lines, brief sleep
                time.sleep(0.1)
                
            except Exception as e:
                recovery_action = self.error_handler.handle_error(e, "file_manager")
                
                if recovery_action == RecoveryAction.RETRY_IMMEDIATE:
                    self._close_file()
                    continue
                    
                elif recovery_action == RecoveryAction.RETRY_WITH_BACKOFF:
                    self._close_file()
                    delay = self.error_handler.get_backoff_delay(
                        self.error_handler.error_contexts.get("file_manager_stream_error", 
                                                            type('obj', (object,), {'attempt_count': 1})).attempt_count
                    )
                    print(f"⏳ Backing off for {delay:.1f}s before retry")
                    time.sleep(delay)
                    continue
                    
                elif recovery_action == RecoveryAction.RESTART_COMPONENT:
                    print("🔄 Restarting file manager component")
                    self._close_file()
                    time.sleep(2)  # Brief pause before restart
                    continue
                    
                elif recovery_action == RecoveryAction.CIRCUIT_BREAKER:
                    print("⚡ Circuit breaker active, pausing file operations")
                    time.sleep(10)
                    continue
                    
                else:  # FATAL_EXIT
                    print(f"💥 Fatal error in file manager: {e}")
                    raise
    
    def _ensure_file_open(self) -> bool:
        """Ensure file is open and ready for reading"""
        if self.current_file is not None:
            return True
            
        if not os.path.exists(self.current_path):
            print(f"⏳ Waiting for log file: {self.current_path}")
            return False
        
        try:
            # Open file for reading
            self.current_file = open(self.current_path, 'r', encoding='utf-8', errors='replace')
            
            # Get file info
            file_stat = os.stat(self.current_path)
            self.current_inode = file_stat.st_ino
            
            # Seek to appropriate position
            file_size = file_stat.st_size
            saved_position = self.state_manager.state.file_position
            saved_inode = self.state_manager.state.file_inode
            
            if saved_inode == self.current_inode and saved_position <= file_size:
                # Same file, seek to saved position
                self.current_file.seek(saved_position)
                self.last_position = saved_position
                print(f"📍 Resumed from position {saved_position}")
            else:
                # Different file or position invalid, start from end
                self.current_file.seek(0, 2)  # Seek to end
                self.last_position = self.current_file.tell()
                print(f"📍 Starting from end of file (position {self.last_position})")
            
            # Update state
            self.state_manager.update_file_position(self.last_position, self.current_inode)
            
            print(f"✅ File opened: {self.current_path} (inode: {self.current_inode})")
            self.error_handler.record_success("file_manager")
            return True
            
        except Exception as e:
            print(f"❌ Failed to open file: {e}")
            self._close_file()
            raise
    
    def _read_lines(self) -> Iterator[str]:
        """Read available lines from file with robust error handling"""
        if self.current_file is None:
            return
        
        try:
            while True:
                # Store position before reading
                pos_before = self.current_file.tell()
                
                try:
                    line = self.current_file.readline()
                except (OSError, IOError) as e:
                    # Handle the specific "underlying stream is not seekable" error
                    if "underlying stream is not seekable" in str(e):
                        print("🔧 Handling stream seekability error")
                        # Close and reopen the file to get a fresh handle
                        self._close_file()
                        raise e  # Let the outer handler manage the recovery
                    else:
                        raise
                
                if not line:
                    # No more lines available
                    break
                
                # Update position tracking
                self.last_position = self.current_file.tell()
                
                # Periodically save position (every 50 lines to balance performance)
                if self.last_position % 50 == 0:
                    self.state_manager.update_file_position(self.last_position, self.current_inode)
                
                yield line.rstrip('\n\r')
                
        except Exception as e:
            # Reset to last known good position if possible
            if hasattr(self, 'last_position'):
                try:
                    self.current_file.seek(self.last_position)
                except:
                    pass  # If seek fails, we'll handle it in the outer loop
            raise
    
    def detect_rotation(self) -> bool:
        """Detect log rotation events"""
        if not self.current_path or not os.path.exists(self.current_path):
            return True  # File disappeared, likely rotated
        
        try:
            current_stat = os.stat(self.current_path)
            current_inode = current_stat.st_ino
            current_size = current_stat.st_size
            
            # Check if inode changed (file was replaced)
            if self.current_inode and current_inode != self.current_inode:
                print(f"🔄 Inode changed: {self.current_inode} → {current_inode}")
                return True
            
            # Check if file size decreased significantly (rotation)
            if self.current_file:
                current_pos = self.current_file.tell()
                if current_size < current_pos - 1000:  # Allow some buffer
                    print(f"🔄 File size decreased: {current_pos} → {current_size}")
                    return True
            
            return False
            
        except (OSError, IOError) as e:
            print(f"⚠️  Error checking file rotation: {e}")
            return True  # Assume rotation on error
    
    def reopen_file(self) -> bool:
        """Safely reopen file after rotation or errors"""
        print("🔄 Reopening file...")
        
        # Close current file
        self._close_file()
        
        # Wait a moment for file system to stabilize
        time.sleep(1)
        
        # Reset position tracking for new file
        self.state_manager.state.file_position = 0
        self.state_manager.state.file_inode = None
        
        # Try to open the file
        return self._ensure_file_open()
    
    def _close_file(self):
        """Safely close current file handle"""
        if self.current_file:
            try:
                # Save final position
                final_pos = self.current_file.tell()
                self.state_manager.update_file_position(final_pos, self.current_inode)
                
                self.current_file.close()
                print("📁 File closed")
            except Exception as e:
                print(f"⚠️  Error closing file: {e}")
            finally:
                self.current_file = None
                self.current_inode = None
    
    def get_file_position(self) -> int:
        """Get current file position for state persistence"""
        if self.current_file:
            try:
                return self.current_file.tell()
            except:
                pass
        return self.last_position
    
    def __del__(self):
        """Cleanup on destruction"""
        self._close_file()