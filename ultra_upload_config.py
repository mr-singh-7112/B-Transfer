#!/usr/bin/env python3
"""
Ultra Upload Configuration
Copyright (c) 2025 Balsim Technologies. All rights reserved.
Proprietary and confidential software.
"""

import os
from typing import Dict, Any

class UltraUploadConfig:
    """Configuration class for ultra-high-speed uploads"""
    
    def __init__(self):
        # Chunk size configuration (1MB default, optimized for Render)
        self.chunk_size = int(os.getenv('UPLOAD_CHUNK_SIZE', 1048576))  # 1MB
        
        # Concurrency settings
        self.max_concurrent_uploads = int(os.getenv('MAX_CONCURRENT_UPLOADS', 10))
        self.max_concurrent_chunks = int(os.getenv('MAX_CONCURRENT_CHUNKS', 5))
        self.max_worker_threads = int(os.getenv('MAX_WORKER_THREADS', 8))
        
        # Performance optimization
        self.enable_compression = os.getenv('ENABLE_COMPRESSION', 'true').lower() == 'true'
        self.enable_parallel_processing = os.getenv('ENABLE_PARALLEL_PROCESSING', 'true').lower() == 'true'
        self.enable_streaming = os.getenv('ENABLE_STREAMING', 'true').lower() == 'true'
        
        # Memory management
        self.max_memory_usage_mb = int(os.getenv('MAX_MEMORY_USAGE_MB', 512))
        self.chunk_buffer_size = int(os.getenv('CHUNK_BUFFER_SIZE', 8192))  # 8KB buffer
        
        # Timeout settings
        self.chunk_upload_timeout = int(os.getenv('CHUNK_UPLOAD_TIMEOUT', 300))  # 5 minutes
        self.session_timeout_hours = int(os.getenv('SESSION_TIMEOUT_HOURS', 24))
        self.assembly_timeout = int(os.getenv('ASSEMBLY_TIMEOUT', 600))  # 10 minutes
        
        # Redis configuration
        self.redis_url = os.getenv('REDIS_URL', None)
        self.redis_ttl_hours = int(os.getenv('REDIS_TTL_HOURS', 24))
        
        # Compression settings
        self.compression_level = int(os.getenv('COMPRESSION_LEVEL', 6))  # 1-9, 6 is balanced
        self.min_compression_size = int(os.getenv('MIN_COMPRESSION_SIZE', 1024))  # 1KB minimum
        
        # Progress tracking
        self.progress_update_interval = float(os.getenv('PROGRESS_UPDATE_INTERVAL', 0.5))  # 500ms
        self.enable_speed_calculation = os.getenv('ENABLE_SPEED_CALCULATION', 'true').lower() == 'true'
        
        # Error handling
        self.max_retry_attempts = int(os.getenv('MAX_RETRY_ATTEMPTS', 3))
        self.retry_delay_seconds = float(os.getenv('RETRY_DELAY_SECONDS', 1.0))
        
        # Security
        self.enable_checksum_validation = os.getenv('ENABLE_CHECKSUM_VALIDATION', 'true').lower() == 'true'
        self.max_file_size_gb = int(os.getenv('MAX_FILE_SIZE_GB', 5))
        
        # Logging
        self.enable_detailed_logging = os.getenv('ENABLE_DETAILED_LOGGING', 'false').lower() == 'true'
        self.log_performance_metrics = os.getenv('LOG_PERFORMANCE_METRICS', 'true').lower() == 'true'
    
    def get_chunk_size_for_file(self, file_size: int) -> int:
        """Dynamically adjust chunk size based on file size"""
        if file_size < 10 * 1024 * 1024:  # < 10MB
            return 512 * 1024  # 512KB chunks
        elif file_size < 100 * 1024 * 1024:  # < 100MB
            return 1024 * 1024  # 1MB chunks
        elif file_size < 1024 * 1024 * 1024:  # < 1GB
            return 2 * 1024 * 1024  # 2MB chunks
        else:  # >= 1GB
            return 4 * 1024 * 1024  # 4MB chunks
    
    def get_optimal_concurrency(self, file_size: int) -> int:
        """Calculate optimal concurrency based on file size and system resources"""
        # Base concurrency
        base_concurrency = min(self.max_concurrent_chunks, 4)
        
        # Adjust based on file size
        if file_size > 1024 * 1024 * 1024:  # > 1GB
            base_concurrency = min(base_concurrency + 2, self.max_concurrent_chunks)
        
        # Adjust based on available memory
        available_memory_mb = self._get_available_memory()
        if available_memory_mb > 2048:  # > 2GB
            base_concurrency = min(base_concurrency + 1, self.max_concurrent_chunks)
        
        return base_concurrency
    
    def _get_available_memory(self) -> int:
        """Get available system memory in MB"""
        try:
            import psutil
            return psutil.virtual_memory().available // (1024 * 1024)
        except ImportError:
            # Fallback to environment variable or default
            return int(os.getenv('AVAILABLE_MEMORY_MB', 1024))
    
    def get_compression_settings(self, file_type: str) -> Dict[str, Any]:
        """Get compression settings optimized for file type"""
        # File types that compress well
        high_compression_types = {'.txt', '.log', '.csv', '.json', '.xml', '.html', '.css', '.js'}
        # File types that don't compress well
        low_compression_types = {'.jpg', '.jpeg', '.png', '.gif', '.heic', '.heif', '.mp4', '.avi', '.mov', '.mp3', '.wav', '.zip', '.rar', '.7z'}
        
        file_ext = os.path.splitext(file_type)[1].lower()
        
        if file_ext in high_compression_types:
            return {
                'enabled': True,
                'level': min(self.compression_level + 2, 9),
                'min_size': self.min_compression_size // 2
            }
        elif file_ext in low_compression_types:
            return {
                'enabled': False,
                'level': self.compression_level,
                'min_size': self.min_compression_size * 4
            }
        else:
            return {
                'enabled': self.enable_compression,
                'level': self.compression_level,
                'min_size': self.min_compression_size
            }
    
    def get_performance_profile(self) -> str:
        """Get current performance profile based on configuration"""
        if self.max_concurrent_uploads >= 10 and self.enable_parallel_processing:
            return 'ultra_high'
        elif self.max_concurrent_uploads >= 5 and self.enable_parallel_processing:
            return 'high'
        elif self.max_concurrent_uploads >= 3:
            return 'medium'
        else:
            return 'standard'
    
    def validate_config(self) -> Dict[str, Any]:
        """Validate configuration and return any warnings"""
        warnings = []
        
        # Check chunk size
        if self.chunk_size < 64 * 1024:  # < 64KB
            warnings.append("Chunk size is very small, may impact performance")
        elif self.chunk_size > 16 * 1024 * 1024:  # > 16MB
            warnings.append("Chunk size is very large, may cause memory issues")
        
        # Check concurrency
        if self.max_concurrent_uploads > 20:
            warnings.append("High concurrency may overwhelm the server")
        
        # Check memory usage
        if self.max_memory_usage_mb < 256:
            warnings.append("Low memory limit may cause upload failures")
        
        # Check timeouts
        if self.chunk_upload_timeout < 60:
            warnings.append("Short chunk timeout may cause upload failures on slow connections")
        
        return {
            'valid': len(warnings) == 0,
            'warnings': warnings,
            'profile': self.get_performance_profile()
        }
    
    def get_optimization_tips(self) -> list:
        """Get optimization tips based on current configuration"""
        tips = []
        
        if not self.enable_compression:
            tips.append("Enable compression for better upload speeds on text-based files")
        
        if not self.enable_parallel_processing:
            tips.append("Enable parallel processing for faster uploads")
        
        if self.chunk_size < 1024 * 1024:  # < 1MB
            tips.append("Consider increasing chunk size to 1MB+ for better performance")
        
        if self.max_concurrent_chunks < 3:
            tips.append("Increase concurrent chunks for better throughput")
        
        if not self.redis_url:
            tips.append("Add Redis for better session management and progress tracking")
        
        return tips
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary"""
        return {
            'chunk_size': self.chunk_size,
            'max_concurrent_uploads': self.max_concurrent_uploads,
            'max_concurrent_chunks': self.max_concurrent_chunks,
            'enable_compression': self.enable_compression,
            'enable_parallel_processing': self.enable_parallel_processing,
            'enable_streaming': self.enable_streaming,
            'max_memory_usage_mb': self.max_memory_usage_mb,
            'chunk_upload_timeout': self.chunk_upload_timeout,
            'session_timeout_hours': self.session_timeout_hours,
            'compression_level': self.compression_level,
            'performance_profile': self.get_performance_profile(),
            'validation': self.validate_config(),
            'optimization_tips': self.get_optimization_tips()
        }

# Global configuration instance
config = UltraUploadConfig()

# Print configuration summary on import
if __name__ != '__main__':
    print("🔧 Ultra Upload Configuration:")
    print(f"   Chunk size: {config.chunk_size // (1024*1024)}MB")
    print(f"   Max concurrent: {config.max_concurrent_uploads}")
    print(f"   Compression: {'✅' if config.enable_compression else '❌'}")
    print(f"   Parallel processing: {'✅' if config.enable_parallel_processing else '❌'}")
    print(f"   Performance profile: {config.get_performance_profile()}")
    
    validation = config.validate_config()
    if not validation['valid']:
        print("⚠️ Configuration warnings:")
        for warning in validation['warnings']:
            print(f"   - {warning}")
    
    if validation['profile'] != 'ultra_high':
        print("💡 Performance optimization tips:")
        for tip in config.get_optimization_tips():
            print(f"   - {tip}") 