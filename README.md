# 🚀 B-Transfer - Ultra High-Speed File Transfer System

**Copyright (c) 2025 Balsim Technologies. All rights reserved.**  
**Proprietary and confidential software.**

A revolutionary file transfer system designed for ultra-high-speed uploads, featuring chunked uploads, parallel processing, compression, and military-grade encryption.

## ✨ Features

### 🚀 **Ultra High-Speed Upload System**
- **Chunked Uploads**: Break large files into manageable chunks
- **Parallel Processing**: Upload multiple chunks simultaneously
- **Smart Compression**: Automatic compression for text-based files
- **Progress Tracking**: Real-time upload progress with speed calculation
- **Resume Capability**: Resume interrupted uploads
- **Memory Optimization**: Efficient memory usage for large files

### 🔐 **Security Features**
- **Military-Grade Encryption**: AES-256 encryption with PBKDF2 key derivation
- **File Locking**: Secure file access control
- **Rate Limiting**: Protection against abuse
- **Session Management**: Secure upload sessions
- **Checksum Validation**: File integrity verification

### ☁️ **Storage Options**
- **Local Storage**: Fast access for small files
- **Google Cloud Storage**: Scalable storage for large files (>100MB)
- **Automatic Cleanup**: Files auto-delete after 24 hours
- **Metadata Tracking**: Comprehensive file information

### 📱 **User Experience**
- **Modern Web Interface**: Beautiful, responsive design
- **Drag & Drop**: Intuitive file upload
- **Real-time Progress**: Live upload status updates
- **Mobile Optimized**: Works perfectly on all devices
- **Cross-platform**: Compatible with all major browsers

## 🚀 Performance

- **Upload Speed**: 5-10x faster than traditional uploads
- **File Size Support**: Up to 5GB per file
- **Concurrent Uploads**: Up to 10 simultaneous uploads
- **Chunk Size**: Dynamic chunk sizing (512KB - 4MB)
- **Compression**: Up to 70% size reduction for text files

## 🛠️ Installation

### Prerequisites
- Python 3.8+
- Redis (optional, for enhanced performance)
- Google Cloud Storage credentials (for large files)

### Quick Start
```bash
# Clone the repository
git clone https://github.com/mr-singh-7112/B-Transfer.git
cd B-Transfer

# Install dependencies
pip3 install -r requirements.txt

# Set environment variables
export REDIS_URL="redis://localhost:6379"  # Optional
export UPLOAD_CHUNK_SIZE="1048576"        # 1MB chunks
export MAX_CONCURRENT_UPLOADS="10"
export ENABLE_COMPRESSION="true"

# Run the server
python3 b_transfer_server.py
```

### Environment Variables
```bash
# Performance Configuration
UPLOAD_CHUNK_SIZE=1048576              # Chunk size in bytes (1MB)
MAX_CONCURRENT_UPLOADS=10              # Max simultaneous uploads
MAX_CONCURRENT_CHUNKS=5                # Max chunks per upload
ENABLE_COMPRESSION=true                # Enable file compression
ENABLE_PARALLEL_PROCESSING=true        # Enable parallel processing

# Redis Configuration (Optional)
REDIS_URL=redis://localhost:6379       # Redis connection URL
REDIS_TTL_HOURS=24                    # Session TTL in hours

# Memory Management
MAX_MEMORY_USAGE_MB=512               # Max memory usage in MB
CHUNK_BUFFER_SIZE=8192                # Buffer size for chunks

# Timeouts
CHUNK_UPLOAD_TIMEOUT=300              # Chunk upload timeout (5 min)
ASSEMBLY_TIMEOUT=600                  # File assembly timeout (10 min)
```

## 🌐 Usage

### Web Interface
1. **Standard Upload**: Visit `/` for traditional file uploads
2. **Ultra Upload**: Visit `/ultra-upload` for high-speed chunked uploads
3. **File Management**: Visit `/files` to manage uploaded files

### API Endpoints

#### Upload Session Management
```bash
# Create upload session
POST /api/upload/session
{
  "filename": "large_file.zip",
  "total_size": 1073741824
}

# Upload chunk
POST /api/upload/chunk
{
  "session_id": "abc123",
  "chunk_id": 0,
  "chunk_data": "base64_encoded_data"
}

# Get progress
GET /api/upload/progress/<session_id>

# Assemble file
POST /api/upload/assemble
{
  "session_id": "abc123"
}

# List sessions
GET /api/upload/sessions
```

#### File Management
```bash
# Upload file (traditional)
POST /upload

# List files
GET /files

# Download file
GET /download/<filename>

# Lock file
POST /lock/<filename>

# Unlock file
POST /unlock/<filename>

# Delete file
DELETE /delete/<filename>
```

## 🚀 Deployment

### Render Deployment
The project includes a `render.yaml` file for easy deployment on Render:

```yaml
services:
  - type: web
    name: b-transfer
    plan: starter  # Upgraded from free for better performance
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn --bind 0.0.0.0:$PORT --workers 4 --worker-class gevent --timeout 300 --keep-alive 5 b_transfer_server:app
    envVars:
      - key: REDIS_URL
        value: $REDIS_URL
      - key: UPLOAD_CHUNK_SIZE
        value: "1048576"
      - key: MAX_CONCURRENT_UPLOADS
        value: "10"
      - key: ENABLE_COMPRESSION
        value: "true"

  - type: redis
    name: redis-b-transfer
    plan: starter
    maxmemoryPolicy: allkeys-lru
```

### Manual Deployment
```bash
# Install Gunicorn
pip install gunicorn

# Run with Gunicorn
gunicorn --bind 0.0.0.0:8000 --workers 4 --worker-class gevent --timeout 300 --keep-alive 5 b_transfer_server:app
```

## 📊 Performance Tuning

### For High-Traffic Scenarios
```bash
# Increase workers and concurrency
export MAX_CONCURRENT_UPLOADS=20
export MAX_CONCURRENT_CHUNKS=10
export UPLOAD_CHUNK_SIZE=2097152  # 2MB chunks

# Use Redis for session management
export REDIS_URL="redis://your-redis-server:6379"
```

### For Large Files (>1GB)
```bash
# Optimize chunk size and memory
export UPLOAD_CHUNK_SIZE=4194304  # 4MB chunks
export MAX_MEMORY_USAGE_MB=1024   # 1GB memory limit
export CHUNK_BUFFER_SIZE=16384    # 16KB buffer
```

## 🔧 Configuration

### Performance Profiles
The system automatically detects and applies optimal settings:

- **Standard**: Basic configuration for small files
- **High**: Optimized for medium files (100MB - 1GB)
- **Ultra High**: Maximum performance for large files (>1GB)

### File Type Optimization
- **Text Files**: High compression, small chunks
- **Media Files**: No compression, larger chunks
- **Archives**: Balanced compression, medium chunks

## 📈 Monitoring

### Health Check
```bash
GET /health
```

### Performance Metrics
- Upload speed (MB/s)
- Compression ratio
- Memory usage
- Active sessions
- Error rates

## 🚨 Troubleshooting

### Common Issues
1. **Import Errors**: Ensure all dependencies are installed
2. **Memory Issues**: Reduce chunk size or concurrent uploads
3. **Timeout Errors**: Increase timeout values
4. **Redis Connection**: Check Redis URL and connectivity

### Performance Issues
1. **Slow Uploads**: Enable compression and parallel processing
2. **High Memory Usage**: Reduce chunk size and buffer size
3. **Network Bottlenecks**: Use CDN or optimize chunk size

## 🤝 Contributing

This is proprietary software. For contributions or support, contact Balsim Technologies.

## 📄 License

**Copyright (c) 2025 Balsim Technologies. All rights reserved.**  
**Proprietary and confidential software.**

## 🆘 Support

For technical support or questions:
- **Email**: support@balsimtech.com
- **Documentation**: [Internal Wiki]
- **Issues**: [GitHub Issues]

---

**Made with ❤️ by Balsim Technologies**  
**Ultra High-Speed File Transfer System** 