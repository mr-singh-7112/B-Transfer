# 🚀 B-Transfer Deployment on Render

## Prerequisites

1. **Render Account**: Sign up at [render.com](https://render.com)
2. **GitHub Repository**: Your B-Transfer project should be on GitHub
3. **Python Knowledge**: Basic understanding of Python web applications

## Deployment Steps

### 1. Connect GitHub Repository

1. Log in to [Render Dashboard](https://dashboard.render.com)
2. Click "New +" → "Web Service"
3. Connect your GitHub account
4. Select the `B-Transfer` repository

### 2. Configure Web Service

- **Name**: `b-transfer` (or your preferred name)
- **Environment**: `Python 3`
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `python3 b_transfer_server.py`
- **Plan**: Free (or choose paid plan for production)

### 3. Environment Variables

Add these environment variables in Render:

- `PORT`: `10000` (Render will set this automatically)
- `RENDER`: `true` (to identify Render deployment)

### 4. Deploy

1. Click "Create Web Service"
2. Render will automatically build and deploy your application
3. Wait for the build to complete (usually 2-5 minutes)

### 5. Access Your Application

- **URL**: `https://your-app-name.onrender.com`
- **Health Check**: `https://your-app-name.onrender.com/health`

## API Endpoints

Once deployed, your B-Transfer API will be available at:

- **Root**: `GET /` - Service information
- **Upload**: `POST /upload` - File upload
- **Download**: `GET /download/<filename>` - File download
- **Files**: `GET /files` - List all files
- **Delete**: `DELETE /delete/<filename>` - Delete file
- **Lock**: `POST /lock/<filename>` - Lock file with password
- **Unlock**: `POST /unlock/<filename>` - Unlock file
- **Health**: `GET /health` - Service health check

## Testing Deployment

### Test Health Endpoint
```bash
curl https://your-app-name.onrender.com/health
```

### Test File Upload
```bash
curl -X POST -F "file=@test.txt" https://your-app-name.onrender.com/upload
```

### Test File Listing
```bash
curl https://your-app-name.onrender.com/files
```

## Important Notes

1. **Free Plan Limitations**: 
   - 750 hours/month
   - Service sleeps after 15 minutes of inactivity
   - 512MB RAM, 0.1 CPU

2. **File Storage**: 
   - Files are stored in Render's ephemeral storage
   - Consider using Google Cloud Storage for persistent storage

3. **Security**: 
   - HTTPS is automatically enabled
   - Rate limiting and security features are active

## Troubleshooting

### Common Issues

1. **Build Failures**: Check requirements.txt and Python version
2. **Port Issues**: Ensure PORT environment variable is set
3. **File Upload Errors**: Check file size limits and allowed extensions

### Logs

- View logs in Render Dashboard → Your Service → Logs
- Monitor for any error messages during deployment

## Support

For Render-specific issues, check [Render Documentation](https://render.com/docs)
For B-Transfer issues, refer to the main README.md

---

**B-Transfer v2.1.0** | **Balsim Technologies** | **Copyright (c) 2025** 