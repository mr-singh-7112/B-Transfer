#!/usr/bin/env python3
"""
Ultra High-Speed Upload System for B-Transfer
Copyright (c) 2025 Balsim Technologies. All rights reserved.
Proprietary and confidential software.
"""

import os
import json
import hashlib
import time
import threading
import asyncio
import aiofiles
import gzip
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple
import redis
from dataclasses import dataclass
from datetime import datetime, timedelta

@dataclass
class UploadChunk:
    """Represents a single chunk of a file upload"""
    chunk_id: int
    data: bytes
    checksum: str
    size: int
    compressed: bool
    upload_time: datetime

@dataclass
class UploadSession:
    """Represents an active upload session"""
    session_id: str
    filename: str
    total_size: int
    chunk_size: int
    total_chunks: int
    uploaded_chunks: Dict[int, UploadChunk]
    start_time: datetime
    last_activity: datetime
    status: str  # 'uploading', 'assembling', 'completed', 'failed'
    compression_enabled: bool
    parallel_processing: bool

class UltraUploadManager:
    """Manages ultra-high-speed file uploads with chunking and parallel processing"""
    
    def __init__(self, redis_url: str = None):
        self.redis_client = None
        if redis_url:
            try:
                self.redis_client = redis.from_url(redis_url)
                self.redis_client.ping()
            except Exception as e:
                print(f"⚠️ Redis connection failed: {e}")
                self.redis_client = None
        
        # Configuration
        self.chunk_size = int(os.getenv('UPLOAD_CHUNK_SIZE', 1048576))  # 1MB chunks
        self.max_concurrent_uploads = int(os.getenv('MAX_CONCURRENT_UPLOADS', 10))
        self.enable_compression = os.getenv('ENABLE_COMPRESSION', 'true').lower() == 'true'
        self.enable_parallel = os.getenv('ENABLE_PARALLEL_PROCESSING', 'true').lower() == 'true'
        
        # Active uploads
        self.active_uploads: Dict[str, UploadSession] = {}
        self.upload_lock = threading.Lock()
        
        # Thread pool for parallel processing
        self.executor = ThreadPoolExecutor(max_workers=self.max_concurrent_uploads)
        
        print(f"🚀 Ultra Upload Manager initialized:")
        print(f"   Chunk size: {self.format_size(self.chunk_size)}")
        print(f"   Max concurrent: {self.max_concurrent_uploads}")
        print(f"   Compression: {'✅' if self.enable_compression else '❌'}")
        print(f"   Parallel processing: {'✅' if self.enable_parallel else '❌'}")
    
    def format_size(self, size_bytes: int) -> str:
        """Format bytes to human readable format"""
        if size_bytes == 0:
            return "0 B"
        size_names = ["B", "KB", "MB", "GB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        return f"{size_bytes:.1f} {size_names[i]}"
    
    def create_upload_session(self, filename: str, total_size: int) -> str:
        """Create a new upload session"""
        session_id = hashlib.sha256(f"{filename}{time.time()}".encode()).hexdigest()[:16]
        
        total_chunks = (total_size + self.chunk_size - 1) // self.chunk_size
        
        session = UploadSession(
            session_id=session_id,
            filename=filename,
            total_size=total_size,
            chunk_size=self.chunk_size,
            total_chunks=total_chunks,
            uploaded_chunks={},
            start_time=datetime.now(),
            last_activity=datetime.now(),
            status='uploading',
            compression_enabled=self.enable_compression,
            parallel_processing=self.enable_parallel
        )
        
        with self.upload_lock:
            self.active_uploads[session_id] = session
        
        # Store in Redis if available
        if self.redis_client:
            try:
                self.redis_client.setex(
                    f"upload_session:{session_id}",
                    3600,  # 1 hour expiry
                    json.dumps({
                        'filename': filename,
                        'total_size': total_size,
                        'total_chunks': total_chunks,
                        'status': 'uploading',
                        'start_time': session.start_time.isoformat()
                    })
                )
            except Exception as e:
                print(f"⚠️ Redis storage failed: {e}")
        
        print(f"📁 Created upload session {session_id} for {filename} ({self.format_size(total_size)})")
        return session_id
    
    def upload_chunk(self, session_id: str, chunk_id: int, chunk_data: bytes) -> Dict:
        """Upload a single chunk"""
        with self.upload_lock:
            if session_id not in self.active_uploads:
                return {'error': 'Upload session not found'}
            
            session = self.active_uploads[session_id]
            
            if chunk_id >= session.total_chunks:
                return {'error': 'Invalid chunk ID'}
            
            if chunk_id in session.uploaded_chunks:
                return {'error': 'Chunk already uploaded'}
        
        # Calculate checksum
        checksum = hashlib.md5(chunk_data).hexdigest()
        
        # Compress chunk if enabled
        compressed = False
        if self.enable_compression and len(chunk_data) > 1024:  # Only compress chunks > 1KB
            try:
                compressed_data = gzip.compress(chunk_data, compresslevel=6)
                if len(compressed_data) < len(chunk_data):
                    chunk_data = compressed_data
                    compressed = True
            except Exception as e:
                print(f"⚠️ Compression failed for chunk {chunk_id}: {e}")
        
        # Create chunk object
        chunk = UploadChunk(
            chunk_id=chunk_id,
            data=chunk_data,
            checksum=checksum,
            size=len(chunk_data),
            compressed=compressed,
            upload_time=datetime.now()
        )
        
        # Store chunk
        with self.upload_lock:
            session.uploaded_chunks[chunk_id] = chunk
            session.last_activity = datetime.now()
        
        # Update Redis progress
        if self.redis_client:
            try:
                progress = len(session.uploaded_chunks) / session.total_chunks * 100
                self.redis_client.setex(
                    f"upload_progress:{session_id}",
                    3600,
                    json.dumps({
                        'uploaded_chunks': len(session.uploaded_chunks),
                        'total_chunks': session.total_chunks,
                        'progress_percent': round(progress, 2),
                        'last_chunk_time': chunk.upload_time.isoformat()
                    })
                )
            except Exception as e:
                print(f"⚠️ Redis progress update failed: {e}")
        
        print(f"📦 Chunk {chunk_id}/{session.total_chunks} uploaded for session {session_id}")
        
        return {
            'status': 'success',
            'chunk_id': chunk_id,
            'checksum': checksum,
            'size': len(chunk_data),
            'compressed': compressed,
            'progress': len(session.uploaded_chunks) / session.total_chunks * 100
        }
    
    def get_upload_progress(self, session_id: str) -> Dict:
        """Get upload progress for a session"""
        with self.upload_lock:
            if session_id not in self.active_uploads:
                return {'error': 'Upload session not found'}
            
            session = self.active_uploads[session_id]
        
        progress = len(session.uploaded_chunks) / session.total_chunks * 100
        elapsed_time = (datetime.now() - session.start_time).total_seconds()
        
        # Calculate speed
        uploaded_bytes = sum(chunk.size for chunk in session.uploaded_chunks.values())
        speed = uploaded_bytes / elapsed_time if elapsed_time > 0 else 0
        
        # Estimate remaining time
        remaining_bytes = session.total_size - uploaded_bytes
        eta = remaining_bytes / speed if speed > 0 else 0
        
        return {
            'session_id': session_id,
            'filename': session.filename,
            'total_size': session.total_size,
            'uploaded_size': uploaded_bytes,
            'total_chunks': session.total_chunks,
            'uploaded_chunks': len(session.uploaded_chunks),
            'progress_percent': round(progress, 2),
            'speed_bps': round(speed, 2),
            'speed_mbps': round(speed / (1024 * 1024), 2),
            'elapsed_time': round(elapsed_time, 2),
            'eta_seconds': round(eta, 2),
            'status': session.status,
            'compression_enabled': session.compression_enabled,
            'parallel_processing': session.parallel_processing
        }
    
    def assemble_file(self, session_id: str, output_path: str) -> Dict:
        """Assemble uploaded chunks into final file"""
        with self.upload_lock:
            if session_id not in self.active_uploads:
                return {'error': 'Upload session not found'}
            
            session = self.active_uploads[session_id]
            
            if len(session.uploaded_chunks) != session.total_chunks:
                return {'error': 'Not all chunks uploaded'}
            
            session.status = 'assembling'
        
        try:
            print(f"🔧 Assembling file from {session.total_chunks} chunks...")
            
            # Sort chunks by ID
            sorted_chunks = sorted(session.uploaded_chunks.values(), key=lambda x: x.chunk_id)
            
            # Create output directory if it doesn't exist
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Assemble file
            with open(output_path, 'wb') as output_file:
                for chunk in sorted_chunks:
                    # Decompress if needed
                    if chunk.compressed:
                        try:
                            decompressed_data = gzip.decompress(chunk.data)
                            output_file.write(decompressed_data)
                        except Exception as e:
                            print(f"❌ Decompression failed for chunk {chunk.chunk_id}: {e}")
                            return {'error': f'Decompression failed: {e}'}
                    else:
                        output_file.write(chunk.data)
            
            # Verify file size
            final_size = os.path.getsize(output_path)
            if final_size != session.total_size:
                print(f"⚠️ Size mismatch: expected {session.total_size}, got {final_size}")
            
            # Update session status
            with self.upload_lock:
                session.status = 'completed'
            
            # Clean up chunks from memory
            with self.upload_lock:
                session.uploaded_chunks.clear()
            
            # Update Redis
            if self.redis_client:
                try:
                    self.redis_client.setex(
                        f"upload_completed:{session_id}",
                        86400,  # 24 hours
                        json.dumps({
                            'filename': session.filename,
                            'final_size': final_size,
                            'completion_time': datetime.now().isoformat(),
                            'total_chunks': session.total_chunks
                        })
                    )
                    self.redis_client.delete(f"upload_progress:{session_id}")
                except Exception as e:
                    print(f"⚠️ Redis completion update failed: {e}")
            
            print(f"✅ File assembled successfully: {output_path} ({self.format_size(final_size)})")
            
            return {
                'status': 'success',
                'filename': session.filename,
                'final_size': final_size,
                'output_path': output_path,
                'total_chunks': session.total_chunks
            }
            
        except Exception as e:
            with self.upload_lock:
                session.status = 'failed'
            
            print(f"❌ File assembly failed: {e}")
            return {'error': f'Assembly failed: {e}'}
    
    def cleanup_session(self, session_id: str):
        """Clean up an upload session"""
        with self.upload_lock:
            if session_id in self.active_uploads:
                session = self.active_uploads[session_id]
                session.uploaded_chunks.clear()
                del self.active_uploads[session_id]
        
        # Clean up Redis
        if self.redis_client:
            try:
                self.redis_client.delete(f"upload_session:{session_id}")
                self.redis_client.delete(f"upload_progress:{session_id}")
            except Exception as e:
                print(f"⚠️ Redis cleanup failed: {e}")
        
        print(f"🧹 Cleaned up upload session {session_id}")
    
    def get_active_sessions(self) -> List[Dict]:
        """Get list of active upload sessions"""
        with self.upload_lock:
            sessions = []
            for session in self.active_uploads.values():
                sessions.append({
                    'session_id': session.session_id,
                    'filename': session.filename,
                    'total_size': session.total_size,
                    'progress': len(session.uploaded_chunks) / session.total_chunks * 100,
                    'status': session.status,
                    'start_time': session.start_time.isoformat()
                })
        return sessions
    
    def cleanup_expired_sessions(self, max_age_hours: int = 24):
        """Clean up expired upload sessions"""
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        
        with self.upload_lock:
            expired_sessions = [
                session_id for session_id, session in self.active_uploads.items()
                if session.last_activity < cutoff_time
            ]
            
            for session_id in expired_sessions:
                self.cleanup_session(session_id)
        
        if expired_sessions:
            print(f"🧹 Cleaned up {len(expired_sessions)} expired sessions")

# Global upload manager instance
upload_manager = UltraUploadManager(os.getenv('REDIS_URL')) 