# 🚀 B-Transfer Deployment Guide

**Copyright (c) 2025 Balsim Technologies. All rights reserved.**  
**Proprietary and confidential software.**

## 📋 Prerequisites

Before deploying B-Transfer, ensure you have:

- [ ] GitHub account with repository access
- [ ] Render account (free tier or higher)
- [ ] Google Cloud Platform account (for cloud storage)
- [ ] Python 3.8+ installed locally
- [ ] Git installed locally

## 🚀 Quick Deploy to Render

### 1. Fork/Clone Repository

```bash
# Clone your repository
git clone https://github.com/YOUR_USERNAME/B-Transfer.git
cd B-Transfer

# Or if you already have it locally
git pull origin main
```

### 2. Configure Google Cloud Storage

1. **Create Service Account:**
   ```bash
   python3 google_cloud_setup.py
   ```

2. **Download service-account.json** to your project root

3. **Enable Cloud Storage API** in Google Cloud Console

### 3. Deploy to Render

1. **Connect Repository:**
   - Go to [Render Dashboard](https://dashboard.render.com/)
   - Click "New +" → "Web Service"
   - Connect your GitHub repository

2. **Configure Service:**
   - **Name:** `b-transfer`
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn --bind 0.0.0.0:$PORT --workers 4 --worker-class gevent --timeout 300 --keep-alive 5 b_transfer_server:app`

3. **Environment Variables:**
   ```env
   GOOGLE_APPLICATION_CREDENTIALS=service-account.json
   UPLOAD_FOLDER=uploads
   MAX_FILE_SIZE=5368709120
   SESSION_TIMEOUT=86400
   RATE_LIMIT_PERIOD=60
   MAX_UPLOADS_PER_SESSION=100
   REDIS_URL=your_redis_url_here
   UPLOAD_CHUNK_SIZE=1048576
   MAX_CONCURRENT_UPLOADS=10
   ENABLE_COMPRESSION=true
   ENABLE_PARALLEL_PROCESSING=true
   ```

4. **Click "Create Web Service"**

### 4. Add Redis Service (Optional but Recommended)

1. **Create Redis Service:**
   - Click "New +" → "Redis"
   - **Name:** `redis-b-transfer`
   - **Plan:** `Starter` ($7/month)

2. **Update Environment Variables:**
   - Copy the Redis URL from the service
   - Update `REDIS_URL` in your web service

## 🔧 Local Development Setup

### 1. Install Dependencies

```bash
pip3 install -r requirements.txt
```

### 2. Run Locally

```bash
python3 b_transfer_server.py
```

**Access URLs:**
- **Local:** http://localhost:8081
- **Network:** http://YOUR_IP:8081

### 3. Test Features

- **Regular Upload:** http://localhost:8081
- **Ultra Upload:** http://localhost:8081/ultra-upload
- **API Health:** http://localhost:8081/health
- **Files API:** http://localhost:8081/api/upload/sessions

## 🌐 Production Deployment

### 1. Render Production Settings

```yaml
# render.yaml (already configured)
services:
  - type: web
    name: b-transfer
    env: python
    plan: starter  # Upgrade from free for better performance
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn --bind 0.0.0.0:$PORT --workers 4 --worker-class gevent --timeout 300 --keep-alive 5 b_transfer_server:app
    envVars:
      - key: PYTHON_VERSION
        value: 3.10.0
      - key: GOOGLE_APPLICATION_CREDENTIALS
        value: service-account.json
      - key: REDIS_URL
        fromService:
          type: redis
          name: redis-b-transfer
```

### 2. Environment Variables

```env
# Core Configuration
GOOGLE_APPLICATION_CREDENTIALS=service-account.json
UPLOAD_FOLDER=uploads
MAX_FILE_SIZE=5368709120
SESSION_TIMEOUT=86400

# Rate Limiting
RATE_LIMIT_PERIOD=60
MAX_UPLOADS_PER_SESSION=100

# Ultra Upload System
REDIS_URL=your_redis_url
UPLOAD_CHUNK_SIZE=1048576
MAX_CONCURRENT_UPLOADS=10
MAX_CONCURRENT_CHUNKS=5
ENABLE_COMPRESSION=true
ENABLE_PARALLEL_PROCESSING=true
ENABLE_STREAMING=true

# Performance Tuning
MAX_WORKER_THREADS=8
CHUNK_BUFFER_SIZE=8192
MAX_MEMORY_USAGE_MB=512
CHUNK_UPLOAD_TIMEOUT=300
ASSEMBLY_TIMEOUT=600

# Security
ENABLE_CHECKSUM_VALIDATION=true
MAX_FILE_SIZE_GB=5
```

### 3. Monitoring & Health Checks

- **Health Endpoint:** `/health`
- **Status Monitoring:** Render provides built-in monitoring
- **Logs:** Available in Render dashboard
- **Metrics:** Response times, error rates, etc.

## 🔒 Security Configuration

### 1. File Upload Security

- **File Type Validation:** Only allowed extensions
- **Size Limits:** Configurable per environment
- **Rate Limiting:** Per-session upload limits
- **Session Management:** Secure session IDs

### 2. Encryption

- **Military-Grade AES-256** for file locking
- **PBKDF2HMAC** key derivation
- **Secure Random** salt generation

### 3. Access Control

- **IP-based Rate Limiting**
- **Session-based Upload Limits**
- **File Access Controls**

## 📊 Performance Optimization

### 1. Upload Speed Improvements

- **Chunked Uploads:** Break large files into manageable pieces
- **Parallel Processing:** Multiple chunks uploaded simultaneously
- **Compression:** Automatic compression for text-based files
- **Streaming:** Process data as it arrives

### 2. Server Configuration

- **Gunicorn Workers:** 4 workers for better concurrency
- **Gevent Worker Class:** Asynchronous I/O handling
- **Timeout Settings:** 5-minute upload timeout
- **Keep-Alive:** Optimized connection handling

### 3. Redis Integration

- **Session Management:** Distributed state management
- **Progress Tracking:** Real-time upload progress
- **Performance Metrics:** Upload speed and ETA calculations

## 🚨 Troubleshooting

### Common Issues

1. **Upload Failures:**
   - Check file size limits
   - Verify Google Cloud credentials
   - Check rate limiting settings

2. **Slow Performance:**
   - Upgrade Render plan from free to starter
   - Enable Redis for better session management
   - Adjust chunk sizes and concurrency

3. **Service Not Starting:**
   - Check environment variables
   - Verify Python version compatibility
   - Check build logs in Render

### Debug Commands

```bash
# Check server health
curl http://localhost:8081/health

# Test ultra upload API
curl http://localhost:8081/api/upload/sessions

# Check server logs
tail -f /var/log/b-transfer.log

# Test file upload
curl -X POST -F "file=@test.txt" http://localhost:8081/upload
```

## 📈 Scaling Considerations

### 1. Render Plan Upgrades

- **Free → Starter:** Better CPU/memory allocation
- **Starter → Standard:** Dedicated resources
- **Standard → Pro:** High-performance instances

### 2. Load Balancing

- **Multiple Instances:** Deploy across regions
- **CDN Integration:** CloudFlare for static assets
- **Database Scaling:** Redis cluster for high availability

### 3. Monitoring & Alerts

- **Uptime Monitoring:** External monitoring services
- **Performance Metrics:** Response time tracking
- **Error Alerting:** Automatic notifications

## 🔄 Continuous Deployment

### 1. GitHub Actions (Optional)

```yaml
# .github/workflows/deploy.yml
name: Deploy to Render
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Deploy to Render
        uses: johnbeynon/render-deploy-action@v1.0.0
        with:
          service-id: ${{ secrets.RENDER_SERVICE_ID }}
          api-key: ${{ secrets.RENDER_API_KEY }}
```

### 2. Manual Deployment

```bash
# Update code
git pull origin main

# Deploy to Render (automatic on push)
git push origin main
```

## 📞 Support & Maintenance

### 1. Regular Maintenance

- **Security Updates:** Keep dependencies updated
- **Performance Monitoring:** Track upload speeds
- **Backup Verification:** Test restore procedures

### 2. Support Resources

- **Documentation:** This guide and README
- **GitHub Issues:** Bug reports and feature requests
- **Render Support:** Platform-specific issues

## 🎯 Success Metrics

### 1. Performance Targets

- **Upload Speed:** 10MB/s+ for large files
- **Response Time:** <200ms for API calls
- **Uptime:** 99.9% availability
- **Concurrent Users:** 100+ simultaneous uploads

### 2. User Experience

- **Progress Tracking:** Real-time upload progress
- **Error Handling:** Clear error messages
- **Retry Functionality:** Automatic retry for failures
- **Mobile Support:** Responsive design

---

**🎉 Congratulations! Your B-Transfer system is now fully deployed and production-ready!**

For additional support or questions, please refer to the README.md or create an issue on GitHub. 