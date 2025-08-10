#!/usr/bin/env python3
"""
B-Transfer Server
Copyright (c) 2025 Balsim Technologies. All rights reserved.
Proprietary and confidential software.
"""

import os
import time
import threading
import hashlib
import secrets
import json
import base64
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_file, session, render_template_string, send_from_directory
from werkzeug.utils import secure_filename
import socket
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from cloud_storage import get_cloud_storage

# Import ultra upload manager
try:
    from ultra_upload import upload_manager
    ULTRA_UPLOAD_AVAILABLE = True
    print("✅ Ultra upload system loaded successfully")
except ImportError as e:
    ULTRA_UPLOAD_AVAILABLE = False
    print(f"⚠️ Ultra upload system not available: {e}")

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)  # Secure session key
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1024  # 10GB limit
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)

# Setup upload directory
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Security settings
MAX_UPLOADS_PER_SESSION = 100  # Increased from 50
MAX_FILE_SIZE_PER_UPLOAD = 5 * 1024 * 1024 * 1024  # 5GB
CLOUD_STORAGE_THRESHOLD = 100 * 1024 * 1024  # 100MB - use cloud for files > 100MB
ALLOWED_EXTENSIONS = {
    'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'heic', 'heif', 'mp4', 'avi', 'mov', 'mp3', 'wav',
    'zip', 'rar', '7z', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'csv'
}

def get_file_size(size_bytes):
    if size_bytes == 0:
        return "0 B"
    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.1f} {size_names[i]}"

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_session_id():
    return hashlib.sha256(secrets.token_bytes(32)).hexdigest()[:16]

def get_client_ip():
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0]
    return request.remote_addr

def log_security_event(event_type, details):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] {event_type}: {details} - IP: {get_client_ip()}\n"
    
    with open('security.log', 'a') as f:
        f.write(log_entry)

# Military-grade encryption functions
def derive_key(password, salt):
    """Derive a key from password using PBKDF2"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    )
    return kdf.derive(password.encode())

def encrypt_file(file_data, password):
    """Encrypt file data with military-grade AES-256"""
    salt = os.urandom(16)
    key = derive_key(password, salt)
    
    # Generate random IV
    iv = os.urandom(16)
    
    # Create cipher
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    
    # Pad data to 16-byte boundary
    padding_length = 16 - (len(file_data) % 16)
    padded_data = file_data + bytes([padding_length] * padding_length)
    
    # Encrypt
    encrypted_data = encryptor.update(padded_data) + encryptor.finalize()
    
    # Create HMAC for integrity
    h = hmac.HMAC(key, hashes.SHA256(), backend=default_backend())
    h.update(iv + encrypted_data)
    mac = h.finalize()
    
    # Combine salt + iv + mac + encrypted_data
    return salt + iv + mac + encrypted_data

def decrypt_file(encrypted_data, password):
    """Decrypt file data with military-grade AES-256"""
    if len(encrypted_data) < 80:  # Minimum size check
        raise ValueError("Invalid encrypted data")
    
    # Extract components
    salt = encrypted_data[:16]
    iv = encrypted_data[16:32]
    mac = encrypted_data[32:64]
    encrypted = encrypted_data[64:]
    
    # Derive key
    key = derive_key(password, salt)
    
    # Verify HMAC
    h = hmac.HMAC(key, hashes.SHA256(), backend=default_backend())
    h.update(iv + encrypted)
    try:
        h.verify(mac)
    except:
        raise ValueError("Invalid password or corrupted data")
    
    # Decrypt
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded_data = decryptor.update(encrypted) + decryptor.finalize()
    
    # Remove padding
    padding_length = padded_data[-1]
    return padded_data[:-padding_length]

def save_file_metadata(filename, metadata):
    """Save file metadata"""
    metadata_file = os.path.join(UPLOAD_FOLDER, f"{filename}.meta")
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f)

def load_file_metadata(filename):
    """Load file metadata"""
    metadata_file = os.path.join(UPLOAD_FOLDER, f"{filename}.meta")
    if os.path.exists(metadata_file):
        with open(metadata_file, 'r') as f:
            return json.load(f)
    return None

# Simple file cleanup (24 hours)
def cleanup_old_files():
    while True:
        try:
            now = time.time()
            for filename in os.listdir(UPLOAD_FOLDER):
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                if os.path.isfile(filepath) and not filename.endswith('.meta'):
                    file_age = now - os.path.getctime(filepath)
                    if file_age > 86400:  # 24 hours
                        os.remove(filepath)
                        # Remove metadata file if exists
                        meta_file = f"{filepath}.meta"
                        if os.path.exists(meta_file):
                            os.remove(meta_file)
                        print(f"🗑️ Auto-deleted: {filename}")
        except Exception as e:
            print(f"⚠️ Cleaner error: {e}")
        time.sleep(3600)  # Check every hour

cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
cleanup_thread.start()

@app.before_request
def security_check():
    # Initialize session
    if 'session_id' not in session:
        session['session_id'] = generate_session_id()
        session['upload_count'] = 0
        session['last_upload'] = None
    
    # Rate limiting
    if request.endpoint == 'upload_file':
        current_time = time.time()
        if session.get('last_upload') and current_time - session['last_upload'] < 3.0:
            log_security_event('RATE_LIMIT', f'Too many uploads from {get_client_ip()}')
            return jsonify({'error': 'Rate limit exceeded. Please wait 3 seconds before uploading again.'}), 429
        
        if session.get('upload_count', 0) >= MAX_UPLOADS_PER_SESSION:
            log_security_event('UPLOAD_LIMIT', f'Upload limit exceeded from {get_client_ip()}')
            return jsonify({'error': 'Upload limit reached for this session.'}), 429

@app.route('/')
def index():
    html_template = '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>B-Transfer Pro - Enterprise File Management</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
        <style>
            :root {
                --primary: #2563eb;
                --primary-dark: #1d4ed8;
                --secondary: #7c3aed;
                --success: #10b981;
                --warning: #f59e0b;
                --danger: #ef4444;
                --info: #06b6d4;
                --light: #f8fafc;
                --dark: #0f172a;
                --gray: #64748b;
                --border: #e2e8f0;
                --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
                --shadow-lg: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
            }
            
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                color: var(--dark);
                line-height: 1.6;
            }
            
            .container {
                max-width: 1400px;
                margin: 0 auto;
                padding: 20px;
            }
            
            .header {
                text-align: center;
                margin-bottom: 40px;
                color: white;
            }
            
            .header h1 {
                font-size: clamp(2.5rem, 5vw, 4rem);
                font-weight: 700;
                margin-bottom: 16px;
                text-shadow: 0 4px 8px rgba(0,0,0,0.3);
                background: linear-gradient(45deg, #fff, #e0e7ff);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
            }
            
            .header p {
                font-size: clamp(1rem, 2.5vw, 1.25rem);
                opacity: 0.9;
                font-weight: 300;
                max-width: 600px;
                margin: 0 auto;
            }
            
            .stats-bar {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 20px;
                margin-bottom: 40px;
            }
            
            .stat-card {
                background: rgba(255, 255, 255, 0.1);
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 16px;
                padding: 24px;
                text-align: center;
                color: white;
                transition: all 0.3s ease;
            }
            
            .stat-card:hover {
                transform: translateY(-4px);
                background: rgba(255, 255, 255, 0.15);
            }
            
            .stat-icon {
                font-size: 2rem;
                margin-bottom: 12px;
                opacity: 0.9;
            }
            
            .stat-number {
                font-size: 2rem;
                font-weight: 700;
                margin-bottom: 8px;
            }
            
            .stat-label {
                font-size: 0.9rem;
                opacity: 0.8;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            
            .main-content {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 30px;
                margin-bottom: 40px;
            }
            
            @media (max-width: 1024px) {
                .main-content {
                    grid-template-columns: 1fr;
                }
            }
            
            .card {
                background: white;
                border-radius: 20px;
                padding: 32px;
                box-shadow: var(--shadow-lg);
                transition: all 0.3s ease;
                border: 1px solid var(--border);
            }
            
            .card:hover {
                transform: translateY(-4px);
                box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
            }
            
            .card h3 {
                color: var(--primary);
                margin-bottom: 24px;
                font-size: 1.5rem;
                font-weight: 600;
                display: flex;
                align-items: center;
                gap: 12px;
            }
            
            .upload-area {
                border: 3px dashed var(--primary);
                border-radius: 16px;
                padding: 48px 24px;
                text-align: center;
                margin-bottom: 24px;
                transition: all 0.3s ease;
                cursor: pointer;
                background: var(--light);
                position: relative;
                overflow: hidden;
            }
            
            .upload-area:hover {
                border-color: var(--secondary);
                background: #f0f4ff;
                transform: scale(1.02);
            }
            
            .upload-area.dragover {
                border-color: var(--secondary);
                background: #e0e7ff;
                transform: scale(1.02);
            }
            
            .upload-area.dragover::before {
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: linear-gradient(45deg, var(--primary), var(--secondary));
                opacity: 0.1;
                z-index: 0;
            }
            
            .upload-content {
                position: relative;
                z-index: 1;
            }
            
            .upload-icon {
                font-size: 3rem;
                color: var(--primary);
                margin-bottom: 16px;
            }
            
            .upload-text {
                font-size: 1.1rem;
                color: var(--gray);
                margin-bottom: 8px;
                font-weight: 500;
            }
            
            .upload-subtext {
                font-size: 0.9rem;
                color: var(--gray);
                opacity: 0.7;
            }
            
            .file-input {
                display: none;
            }
            
            .btn {
                background: linear-gradient(45deg, var(--primary), var(--secondary));
                color: white;
                border: none;
                padding: 16px 32px;
                border-radius: 12px;
                font-size: 1rem;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s ease;
                display: inline-flex;
                align-items: center;
                gap: 8px;
                text-decoration: none;
                box-shadow: var(--shadow);
            }
            
            .btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 10px 25px rgba(37, 99, 235, 0.3);
            }
            
            .btn:active {
                transform: translateY(0);
            }
            
            .btn-secondary {
                background: var(--light);
                color: var(--dark);
                border: 1px solid var(--border);
            }
            
            .btn-secondary:hover {
                background: var(--border);
                box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
            }
            
            .btn-success { 
                background: var(--success); 
                transition: all 0.2s ease;
            }
            .btn-success:hover { 
                background: #059669; 
                transform: translateY(-1px);
            }
            
            .btn-warning { 
                background: var(--warning); 
                transition: all 0.2s ease;
            }
            .btn-warning:hover { 
                background: #d97706; 
                transform: translateY(-1px);
            }
            
            .btn-danger { 
                background: var(--danger); 
                transition: all 0.2s ease;
            }
            .btn-danger:hover { 
                background: #dc2626; 
                transform: translateY(-1px);
            }
            
            .btn-info { 
                background: var(--info); 
                transition: all 0.2s ease;
            }
            .btn-info:hover { 
                background: #0891b2; 
                transform: translateY(-1px);
            }
            
            .files-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 24px;
                flex-wrap: wrap;
                gap: 16px;
            }
            
            .search-box {
                position: relative;
                flex: 1;
                max-width: 300px;
            }
            
            .search-controls {
                display: flex;
                align-items: center;
                gap: 16px;
                flex-wrap: wrap;
            }
            
            .sort-controls {
                display: flex;
                align-items: center;
                gap: 8px;
            }
            
            .sort-controls label {
                font-size: 0.9rem;
                color: var(--gray);
                font-weight: 500;
            }
            
            .sort-select {
                padding: 8px 12px;
                border: 1px solid var(--border);
                border-radius: 8px;
                font-size: 0.85rem;
                background: white;
                color: var(--dark);
                cursor: pointer;
                transition: all 0.3s ease;
            }
            
            .sort-select:focus {
                outline: none;
                border-color: var(--primary);
                box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.1);
            }
            
            .sort-select:hover {
                border-color: var(--primary);
            }
            
            .search-input {
                width: 100%;
                padding: 12px 16px 12px 44px;
                border: 1px solid var(--border);
                border-radius: 12px;
                font-size: 0.9rem;
                transition: all 0.3s ease;
            }
            
            .search-input:focus {
                outline: none;
                border-color: var(--primary);
                box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
            }
            
            .search-icon {
                position: absolute;
                left: 16px;
                top: 50%;
                transform: translateY(-50%);
                color: var(--gray);
            }
            
            .files-list {
                max-height: 500px;
                overflow-y: auto;
                scrollbar-width: thin;
                scrollbar-color: var(--border) transparent;
            }
            
            .files-list::-webkit-scrollbar {
                width: 6px;
            }
            
            .files-list::-webkit-scrollbar-track {
                background: transparent;
            }
            
            .files-list::-webkit-scrollbar-thumb {
                background: var(--border);
                border-radius: 3px;
            }
            
            .file-item {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 20px;
                border: 1px solid var(--border);
                border-radius: 12px;
                margin-bottom: 16px;
                background: var(--light);
                transition: all 0.3s ease;
                position: relative;
            }
            
            .file-item:hover {
                background: white;
                border-color: var(--primary);
                box-shadow: var(--shadow);
                transform: translateX(4px);
            }
            
            .file-info {
                flex: 1;
                min-width: 0;
            }
            
            .file-name {
                font-weight: 600;
                color: var(--dark);
                margin-bottom: 8px;
                font-size: 1rem;
                word-break: break-word;
            }
            
            .file-meta {
                display: flex;
                align-items: center;
                gap: 16px;
                flex-wrap: wrap;
                font-size: 0.85rem;
                color: var(--gray);
            }
            
            .file-meta-item {
                display: flex;
                align-items: center;
                gap: 6px;
            }
            
            .file-actions {
                display: flex;
                gap: 8px;
                flex-wrap: wrap;
            }
            
            .action-btn {
                padding: 8px 16px;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                font-size: 0.85rem;
                font-weight: 500;
                transition: all 0.3s ease;
                display: flex;
                align-items: center;
                gap: 6px;
                min-width: 80px;
                justify-content: center;
            }
            
            .action-btn:hover {
                transform: translateY(-2px);
                box-shadow: var(--shadow);
            }
            
            .status {
                padding: 12px 20px;
                border-radius: 12px;
                margin: 16px 0;
                text-align: center;
                font-weight: 500;
                animation: slideIn 0.3s ease;
            }
            
            @keyframes slideIn {
                from { opacity: 0; transform: translateY(-10px); }
                to { opacity: 1; transform: translateY(0); }
            }
            
            .status.success {
                background: #dcfce7;
                color: var(--success);
                border: 1px solid #bbf7d0;
            }
            
            .status.error {
                background: #fef2f2;
                color: var(--danger);
                border: 1px solid #fecaca;
            }
            
            .status.info {
                background: #dbeafe;
                color: var(--info);
                border: 1px solid #bfdbfe;
            }
            
            .upload-queue {
                margin: 16px 0;
                border: 1px solid var(--border);
                border-radius: 12px;
                padding: 16px;
                background: var(--light);
            }
            
            .upload-queue h4 {
                margin: 0 0 16px 0;
                color: var(--dark);
                font-size: 1rem;
                display: flex;
                align-items: center;
                gap: 8px;
            }
            
            .queue-items {
                max-height: 200px;
                overflow-y: auto;
            }
            
            .queue-item {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 12px;
                border: 1px solid var(--border);
                border-radius: 8px;
                margin-bottom: 8px;
                background: white;
                transition: all 0.3s ease;
            }
            
            .queue-file-info {
                display: flex;
                align-items: center;
                gap: 12px;
                flex: 1;
            }
            
            .queue-filename {
                font-weight: 500;
                color: var(--dark);
                max-width: 200px;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            
            .queue-size {
                color: var(--gray);
                font-size: 0.875rem;
            }
            
            .queue-status {
                display: flex;
                flex-direction: column;
                align-items: flex-end;
                gap: 8px;
                min-width: 120px;
            }
            
            .status-text {
                font-size: 0.875rem;
                font-weight: 500;
                padding: 4px 8px;
                border-radius: 4px;
                text-align: center;
                min-width: 80px;
            }
            
            .status-text.queued {
                background: #f3f4f6;
                color: #6b7280;
            }
            
            .status-text.uploading {
                background: #dbeafe;
                color: #1d4ed8;
            }
            
            .status-text.completed {
                background: #dcfce7;
                color: #059669;
            }
            
            .status-text.failed {
                background: #fef2f2;
                color: #dc2626;
            }
            
            .queue-progress {
                width: 100px;
            }
            
            .queue-progress .progress-bar {
                width: 100%;
                height: 6px;
                background: var(--border);
                border-radius: 3px;
                overflow: hidden;
                margin-bottom: 4px;
            }
            
            .queue-progress .progress-fill {
                height: 100%;
                background: linear-gradient(45deg, var(--primary), var(--secondary));
                width: 0%;
                transition: width 0.3s ease;
                border-radius: 3px;
            }
            
            .queue-progress .progress-text {
                font-size: 0.75rem;
                color: var(--gray);
                text-align: center;
            }
            
            .retry-btn {
                background: var(--warning);
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-size: 0.75rem;
                cursor: pointer;
                transition: all 0.3s ease;
                display: none;
            }
            
            .retry-btn:hover {
                background: #d97706;
                transform: translateY(-1px);
            }
            
            .remove-btn {
                background: var(--danger);
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-size: 0.75rem;
                cursor: pointer;
                transition: all 0.3s ease;
                display: none;
                margin-left: 8px;
            }
            
            .remove-btn:hover {
                background: #dc2626;
                transform: translateY(-1px);
            }
            
            .empty-state {
                text-align: center;
                padding: 48px 24px;
                color: var(--gray);
            }
            
            .empty-icon {
                font-size: 3rem;
                margin-bottom: 16px;
                opacity: 0.5;
            }
            
            .empty-text {
                font-size: 1.1rem;
                margin-bottom: 8px;
                font-weight: 500;
            }
            
            .empty-subtext {
                font-size: 0.9rem;
                opacity: 0.7;
            }
            
            .footer {
                text-align: center;
                color: white;
                margin-top: 60px;
                opacity: 0.8;
                padding: 24px;
                border-top: 1px solid rgba(255, 255, 255, 0.1);
            }
            
            .footer p {
                margin-bottom: 8px;
            }
            
            .footer a {
                color: white;
                text-decoration: none;
                opacity: 0.8;
                transition: opacity 0.3s ease;
            }
            
            .footer a:hover {
                opacity: 1;
            }
            
            .loading {
                display: inline-block;
                width: 20px;
                height: 20px;
                border: 3px solid rgba(255,255,255,.3);
                border-radius: 50%;
                border-top-color: #fff;
                animation: spin 1s ease-in-out infinite;
            }
            
            @keyframes spin {
                to { transform: rotate(360deg); }
            }
            
            .file-type-icon {
                width: 40px;
                height: 40px;
                background: var(--primary);
                border-radius: 8px;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-size: 1.2rem;
                margin-right: 16px;
            }
            
            .file-item-content {
                display: flex;
                align-items: center;
                flex: 1;
                min-width: 0;
            }
            
            @media (max-width: 768px) {
                .container { padding: 16px; }
                .card { padding: 24px; }
                .upload-area { padding: 32px 16px; }
                .file-item { flex-direction: column; align-items: stretch; gap: 16px; }
                .file-actions { justify-content: center; }
                .stats-bar { grid-template-columns: repeat(2, 1fr); }
                .files-header { flex-direction: column; align-items: stretch; }
                .search-box { max-width: none; }
            }
            
            @media (max-width: 480px) {
                .stats-bar { grid-template-columns: 1fr; }
                .action-btn { min-width: 70px; padding: 6px 12px; font-size: 0.8rem; }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1><i class="fas fa-rocket"></i> B-Transfer Pro</h1>
                <p>Enterprise-grade secure file management with military-grade encryption</p>
            </div>
            
            <div class="stats-bar">
                <div class="stat-card">
                    <div class="stat-icon"><i class="fas fa-shield-alt"></i></div>
                    <div class="stat-number" id="totalFiles">0</div>
                    <div class="stat-label">Total Files</div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon"><i class="fas fa-lock"></i></div>
                    <div class="stat-number" id="lockedFiles">0</div>
                    <div class="stat-label">Locked Files</div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon"><i class="fas fa-cloud"></i></div>
                    <div class="stat-number" id="cloudFiles">0</div>
                    <div class="stat-label">Cloud Storage</div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon"><i class="fas fa-clock"></i></div>
                    <div class="stat-number">24h</div>
                    <div class="stat-label">Auto-Cleanup</div>
                </div>
            </div>
            
            <div class="main-content">
                <div class="card">
                    <h3><i class="fas fa-cloud-upload-alt"></i> Upload Files</h3>
                    <div class="upload-area" id="uploadArea">
                        <div class="upload-content">
                            <div class="upload-icon"><i class="fas fa-cloud-upload-alt"></i></div>
                            <div class="upload-text">Drag & drop files here</div>
                            <div class="upload-subtext">or click to browse files</div>
                        </div>
                        <input type="file" id="fileInput" class="file-input" multiple>
                    </div>
                    <button class="btn" onclick="document.getElementById('fileInput').click()">
                        <i class="fas fa-folder-open"></i> Choose Files
                    </button>
                    <div id="uploadStatus"></div>
                    <div class="upload-queue" id="uploadQueue">
                        <h4><i class="fas fa-list"></i> Upload Queue</h4>
                        <div id="queueStatus" class="queue-status"></div>
                        <div class="queue-items" id="queueItems"></div>
                    </div>
                </div>
                
                <div class="card">
                    <div class="files-header">
                        <h3><i class="fas fa-folder-open"></i> File Management</h3>
                        <div class="search-controls">
                            <div class="search-box">
                                <i class="fas fa-search search-icon"></i>
                                <input type="text" class="search-input" id="searchInput" placeholder="Search files...">
                            </div>
                            <div class="sort-controls">
                                <label for="sortSelect">Sort by:</label>
                                <select id="sortSelect" class="sort-select" onchange="sortFiles()">
                                    <option value="upload_time_desc">Last Added (Newest)</option>
                                    <option value="upload_time_asc">Last Added (Oldest)</option>
                                    <option value="size_asc">Size (Smallest First)</option>
                                    <option value="size_desc">Size (Largest First)</option>
                                    <option value="name_asc">Name (A-Z)</option>
                                    <option value="name_desc">Name (Z-A)</option>
                                </select>
                            </div>
                            <button class="btn btn-secondary" onclick="refreshFiles()">
                                <i class="fas fa-sync-alt"></i> Refresh
                            </button>
                        </div>
                    </div>
                    <div id="filesList" class="files-list"></div>
                </div>
            </div>
            
            <div class="footer">
                <p><strong>© 2025 Balsim Technologies. All rights reserved.</strong></p>
                <p>Proprietary and confidential software | Military-grade encryption | Cloud storage integration</p>
                <p><a href="/health">API Health</a> | <a href="/files">Files API</a></p>
            </div>
        </div>

        <script>
            const API_BASE = window.location.origin;
            let currentFiles = [];
            let searchTimeout;
            let currentSort = 'upload_time_desc'; // Default sort: newest first
            
            // Initialize
            document.addEventListener('DOMContentLoaded', function() {
                refreshFiles();
                setupEventListeners();
                updateStats();
            });
            
            function setupEventListeners() {
                const uploadArea = document.getElementById('uploadArea');
                const fileInput = document.getElementById('fileInput');
                const searchInput = document.getElementById('searchInput');
                
                // Drag and drop
                uploadArea.addEventListener('dragover', handleDragOver);
                uploadArea.addEventListener('dragleave', handleDragLeave);
                uploadArea.addEventListener('drop', handleDrop);
                uploadArea.addEventListener('click', () => fileInput.click());
                
                // File input
                fileInput.addEventListener('change', handleFileSelect);
                
                // Search
                searchInput.addEventListener('input', handleSearch);
            }
            
            function handleDragOver(e) {
                e.preventDefault();
                e.currentTarget.classList.add('dragover');
            }
            
            function handleDragLeave(e) {
                e.currentTarget.classList.remove('dragover');
            }
            
            function handleDrop(e) {
                e.preventDefault();
                e.currentTarget.classList.remove('dragover');
                const files = e.dataTransfer.files;
                handleFiles(files);
            }
            
            function handleFileSelect(e) {
                const files = e.target.files;
                handleFiles(files);
            }
            
            // Upload queue management with smart prioritization
            let uploadQueue = [];
            let isUploading = false;
            let failedUploads = new Set(); // Track failed uploads to avoid infinite retries
            
            function handleFiles(files) {
                Array.from(files).forEach(file => {
                    addToUploadQueue(file);
                });
                
                // Start processing queue if not already running
                if (!isUploading) {
                    processUploadQueue();
                }
            }
            
            function addToUploadQueue(file) {
                uploadQueue.push(file);
                // Sort queue by file size (smaller files first) for better user experience
                sortUploadQueue();
                displayQueueItem(file);
            }
            
            function sortUploadQueue() {
                // Sort by file size: smaller files first, then by upload time
                uploadQueue.sort((a, b) => {
                    if (a.size !== b.size) {
                        return a.size - b.size; // Smaller files first
                    }
                    // If same size, maintain upload order (FIFO)
                    return uploadQueue.indexOf(a) - uploadQueue.indexOf(b);
                });
            }
            
            function displayQueueItem(file) {
                const queueItems = document.getElementById('queueItems');
                const queueItem = document.createElement('div');
                queueItem.className = 'queue-item';
                queueItem.id = `queue-${file.name.replace(/[^a-zA-Z0-9]/g, '_')}`;
                queueItem.innerHTML = `
                    <div class="queue-file-info">
                        <i class="fas ${getFileIcon(file.name)}"></i>
                        <span class="queue-filename">${file.name}</span>
                        <span class="queue-size">${formatFileSize(file.size)}</span>
                    </div>
                    <div class="queue-status">
                        <span class="status-text queued">Queued</span>
                        <div class="queue-progress" style="display: none;">
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: 0%"></div>
                            </div>
                            <span class="progress-text">0%</span>
                        </div>
                        <button class="retry-btn" style="display: none;" onclick="retryUpload('${file.name.replace(/'/g, "\\'")}')">
                            <i class="fas fa-redo"></i> Retry
                        </button>
                        <button class="remove-btn" style="display: none;" onclick="removeFailedUpload('${file.name.replace(/'/g, "\\'")}')">
                            <i class="fas fa-times"></i> Remove
                        </button>
                    </div>
                `;
                queueItems.appendChild(queueItem);
            }
            
            async function processUploadQueue() {
                if (uploadQueue.length === 0) {
                    isUploading = false;
                    return;
                }
                
                isUploading = true;
                const file = uploadQueue.shift();
                
                // Update status to uploading
                const queueItem = document.getElementById(`queue-${file.name.replace(/[^a-zA-Z0-9]/g, '_')}`);
                if (queueItem) {
                    const statusText = queueItem.querySelector('.status-text');
                    const progressContainer = queueItem.querySelector('.queue-progress');
                    
                    statusText.textContent = 'Uploading...';
                    statusText.className = 'status-text uploading';
                    progressContainer.style.display = 'block';
                    
                    try {
                        await uploadFile(file, queueItem);
                        // Mark as successful and remove from failed uploads if it was there
                        failedUploads.delete(file.name);
                    } catch (error) {
                        console.error('Upload error:', error);
                        // Mark as failed and add to failed uploads set
                        failedUploads.add(file.name);
                        
                        // Update queue item to show failure and retry button
                        if (queueItem) {
                            const statusText = queueItem.querySelector('.status-text');
                            const retryBtn = queueItem.querySelector('.retry-btn');
                            const removeBtn = queueItem.querySelector('.remove-btn');
                            
                            statusText.textContent = 'Failed';
                            statusText.className = 'status-text failed';
                            if (retryBtn) retryBtn.style.display = 'inline-block';
                            if (removeBtn) removeBtn.style.display = 'inline-block';
                        }
                    }
                }
                
                // Process next file in queue immediately (no delay for failed uploads)
                processUploadQueue();
            }
            
            function handleSearch(e) {
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(() => {
                    const searchTerm = e.target.value.toLowerCase();
                    const filteredFiles = currentFiles.filter(file => 
                        file.filename.toLowerCase().includes(searchTerm)
                    );
                    displayFiles(filteredFiles);
                }, 300);
            }
            
            function retryUpload(filename) {
                // Find the file in the queue and retry
                const queueItem = document.getElementById(`queue-${filename.replace(/[^a-zA-Z0-9]/g, '_')}`);
                if (queueItem) {
                    // Reset status
                    const statusText = queueItem.querySelector('.status-text');
                    const progressContainer = queueItem.querySelector('.queue-progress');
                    const retryBtn = queueItem.querySelector('.retry-btn');
                    
                    statusText.textContent = 'Retrying...';
                    statusText.className = 'status-text uploading';
                    if (progressContainer) progressContainer.style.display = 'none';
                    if (retryBtn) retryBtn.style.display = 'none';
                    
                    // Create a new file object for retry (since the original might be consumed)
                    const originalFile = queueItem.querySelector('.queue-file-info');
                    if (originalFile) {
                        // Create a new file object with the same name and size
                        const fileSize = queueItem.querySelector('.queue-size').textContent;
                        const file = new File([], filename, { type: 'application/octet-stream' });
                        file.size = parseFileSize(fileSize);
                        
                        // Remove from failed uploads set
                        failedUploads.delete(filename);
                        
                        // Add to front of queue for immediate processing (priority retry)
                        uploadQueue.unshift(file);
                        if (!isUploading) {
                            processUploadQueue();
                        }
                    }
                }
            }
            
            function removeFailedUpload(filename) {
                // Remove failed upload from queue display
                const queueItem = document.getElementById(`queue-${filename.replace(/[^a-zA-Z0-9]/g, '_')}`);
                if (queueItem) {
                    queueItem.remove();
                }
                
                // Remove from failed uploads set
                failedUploads.delete(filename);
                
                // Continue processing queue if there are more files
                if (uploadQueue.length > 0 && !isUploading) {
                    processUploadQueue();
                }
            }
            
            function getQueueStatus() {
                const total = uploadQueue.length;
                const failed = failedUploads.size;
                const processing = isUploading ? 1 : 0;
                const queued = total - processing - failed;
                
                return {
                    total,
                    queued,
                    processing,
                    failed
                };
            }
            
            function updateQueueStatus() {
                const status = getQueueStatus();
                const statusElement = document.getElementById('queueStatus');
                if (statusElement) {
                    statusElement.innerHTML = `
                        <div class="queue-status-info">
                            <span class="status-item">
                                <i class="fas fa-clock"></i> Queued: ${status.queued}
                            </span>
                            <span class="status-item">
                                <i class="fas fa-sync-alt"></i> Processing: ${status.processing}
                            </span>
                            <span class="status-item">
                                <i class="fas fa-exclamation-triangle"></i> Failed: ${status.failed}
                            </span>
                        </div>
                    `;
                }
            }
            
            function parseFileSize(sizeStr) {
                const units = { 'B': 1, 'KB': 1024, 'MB': 1024*1024, 'GB': 1024*1024*1024 };
                const match = sizeStr.match(/^([\d.]+)\s*([KMGT]?B)$/);
                if (match) {
                    const value = parseFloat(match[1]);
                    const unit = match[2] || 'B';
                    return Math.round(value * units[unit]);
                }
                return 0;
            }
            
            async function uploadFile(file, queueItem) {
                const formData = new FormData();
                formData.append('file', file);
                
                const statusDiv = document.getElementById('uploadStatus');
                statusDiv.innerHTML = `<div class="status info">📤 Uploading ${file.name}...</div>`;
                
                return new Promise((resolve, reject) => {
                    const xhr = new XMLHttpRequest();
                    
                    xhr.upload.addEventListener('progress', (event) => {
                        if (event.lengthComputable) {
                            const progress = Math.round((event.loaded / event.total) * 100);
                            updateQueueProgress(file.name, progress, queueItem);
                        }
                    });
                    
                    xhr.addEventListener('load', () => {
                        if (xhr.status === 200) {
                            // Update status to completed
                            const statusText = queueItem.querySelector('.status-text');
                            statusText.textContent = 'Completed';
                            statusText.className = 'status-text completed';
                            
                            statusDiv.innerHTML = `<div class="status success">✅ ${file.name} uploaded successfully!</div>`;
                            refreshFiles();
                            updateStats();
                            
                            // Remove from queue after delay
                            setTimeout(() => {
                                if (queueItem.parentNode) {
                                    queueItem.remove();
                                }
                            }, 5000);
                            
                            resolve();
                        } else {
                            // Update status to failed
                            const statusText = queueItem.querySelector('.status-text');
                            statusText.textContent = 'Failed';
                            statusText.className = 'status-text failed';
                            
                            // Show retry button
                            const retryBtn = queueItem.querySelector('.retry-btn');
                            if (retryBtn) retryBtn.style.display = 'inline-block';
                            
                            // Try to parse error message from response
                            let errorMessage = 'Upload failed';
                            try {
                                const response = JSON.parse(xhr.responseText);
                                if (response.error) {
                                    errorMessage = response.error;
                                }
                            } catch (e) {
                                // If can't parse JSON, use status text
                                errorMessage = xhr.statusText || 'Upload failed';
                            }
                            
                            statusDiv.innerHTML = `<div class="status error">❌ Error uploading ${file.name}: ${errorMessage}</div>`;
                            reject(new Error(errorMessage));
                        }
                        
                        setTimeout(() => {
                            statusDiv.innerHTML = '';
                        }, 5000);
                    });
                    
                    xhr.addEventListener('error', () => {
                        const statusText = queueItem.querySelector('.status-text');
                        statusText.textContent = 'Failed';
                        statusText.className = 'status-text failed';
                        
                        // Show retry button
                        const retryBtn = queueItem.querySelector('.retry-btn');
                        if (retryBtn) retryBtn.style.display = 'inline-block';
                        
                        statusDiv.innerHTML = `<div class="status error">❌ Network error uploading ${file.name}. Please check your connection.</div>`;
                        reject(new Error('Network error'));
                        
                        setTimeout(() => {
                            statusDiv.innerHTML = '';
                        }, 5000);
                    });
                    
                    xhr.open('POST', `${API_BASE}/upload`);
                    xhr.timeout = 300000; // 5 minutes timeout
                    
                    xhr.addEventListener('timeout', () => {
                        const statusText = queueItem.querySelector('.status-text');
                        statusText.textContent = 'Failed';
                        statusText.className = 'status-text failed';
                        
                        // Show retry button
                        const retryBtn = queueItem.querySelector('.retry-btn');
                        if (retryBtn) retryBtn.style.display = 'inline-block';
                        
                        statusDiv.innerHTML = `<div class="status error">❌ Upload timeout for ${file.name}. File may be too large.</div>`;
                        reject(new Error('Upload timeout'));
                        
                        setTimeout(() => {
                            statusDiv.innerHTML = '';
                        }, 5000);
                    });
                    
                    xhr.send(formData);
                });
            }
            
            function updateQueueProgress(filename, progress, queueItem) {
                const progressFill = queueItem.querySelector('.progress-fill');
                const progressText = queueItem.querySelector('.progress-text');
                
                if (progressFill && progressText) {
                    progressFill.style.width = `${progress}%`;
                    progressText.textContent = `${progress}%`;
                }
            }
            
            async function refreshFiles() {
                try {
                    const response = await fetch(`${API_BASE}/files`);
                    const files = await response.json();
                    currentFiles = files;
                    
                    // Apply current sort to the loaded files
                    sortFiles();
                    updateStats();
                } catch (error) {
                    console.error('Error fetching files:', error);
                    showError('Failed to load files');
                }
            }
            
            function displayFiles(files) {
                const filesList = document.getElementById('filesList');
                
                if (files.length === 0) {
                    filesList.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-icon"><i class="fas fa-folder-open"></i></div>
                            <div class="empty-text">No files uploaded yet</div>
                            <div class="empty-subtext">Upload your first file to get started</div>
                        </div>
                    `;
                    return;
                }
                
                filesList.innerHTML = files.map(file => `
                    <div class="file-item" data-filename="${file.filename}">
                        <div class="file-item-content">
                            <div class="file-type-icon">
                                <i class="fas ${getFileIcon(file.filename)}"></i>
                            </div>
                            <div class="file-info">
                                <div class="file-name">${escapeHtml(file.filename)}</div>
                                <div class="file-meta">
                                    <span class="file-meta-item">
                                        <i class="fas fa-weight-hanging"></i> ${formatFileSize(file.size)}
                                    </span>
                                    <span class="file-meta-item">
                                        <i class="fas fa-calendar"></i> ${formatDate(file.upload_time)}
                                    </span>
                                    <span class="file-meta-item">
                                        <i class="fas ${file.is_locked ? 'fa-lock' : 'fa-unlock'}"></i> 
                                        ${file.is_locked ? 'Locked' : 'Unlocked'}
                                    </span>
                                </div>
                            </div>
                        </div>
                        <div class="file-actions">
                            <button class="action-btn btn-success" onclick="downloadFile('${escapeHtml(file.filename)}')">
                                <i class="fas fa-download"></i> Download
                            </button>
                            ${file.is_locked ? 
                                `<button class="action-btn btn-info" onclick="unlockFile('${escapeHtml(file.filename)}')">
                                    <i class="fas fa-unlock"></i> Unlock
                                </button>` :
                                `<button class="action-btn btn-warning" onclick="lockFile('${escapeHtml(file.filename)}')">
                                    <i class="fas fa-lock"></i> Lock
                                </button>`
                            }
                            <button class="action-btn btn-danger" onclick="deleteFile('${escapeHtml(file.filename)}')">
                                <i class="fas fa-trash"></i> Delete
                            </button>
                        </div>
                    </div>
                `).join('');
            }
            
            function formatFileSize(bytes) {
                if (bytes === 0) return '0 Bytes';
                const k = 1024;
                const sizes = ['Bytes', 'KB', 'MB', 'GB'];
                const i = Math.floor(Math.log(bytes) / Math.log(k));
                return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
            }
            
            function formatDate(dateString) {
                const date = new Date(dateString);
                const now = new Date();
                const diffTime = Math.abs(now - date);
                const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
                
                if (diffDays === 1) return 'Today';
                if (diffDays === 2) return 'Yesterday';
                if (diffDays <= 7) return `${diffDays - 1} days ago`;
                
                return date.toLocaleDateString();
            }
            
            function getFileIcon(filename) {
                const ext = filename.split('.').pop().toLowerCase();
                const iconMap = {
                    'pdf': 'fa-file-pdf',
                    'doc': 'fa-file-word',
                    'docx': 'fa-file-word',
                    'xls': 'fa-file-excel',
                    'xlsx': 'fa-file-excel',
                    'ppt': 'fa-file-powerpoint',
                    'pptx': 'fa-file-powerpoint',
                    'txt': 'fa-file-alt',
                    'jpg': 'fa-file-image',
                    'jpeg': 'fa-file-image',
                    'png': 'fa-file-image',
                    'gif': 'fa-file-image',
                    'heic': 'fa-file-image',
                    'heif': 'fa-file-image',
                    'mp4': 'fa-file-video',
                    'avi': 'fa-file-video',
                    'mov': 'fa-file-video',
                    'zip': 'fa-file-archive',
                    'rar': 'fa-file-archive',
                    'mp3': 'fa-file-audio',
                    'wav': 'fa-file-audio'
                };
                return iconMap[ext] || 'fa-file';
            }
            
            function sortFiles() {
                const sortSelect = document.getElementById('sortSelect');
                currentSort = sortSelect.value;
                
                // Apply sorting to current files
                const sortedFiles = [...currentFiles];
                
                switch (currentSort) {
                    case 'upload_time_desc':
                        sortedFiles.sort((a, b) => new Date(b.upload_time) - new Date(a.upload_time));
                        break;
                    case 'upload_time_asc':
                        sortedFiles.sort((a, b) => new Date(a.upload_time) - new Date(b.upload_time));
                        break;
                    case 'size_asc':
                        sortedFiles.sort((a, b) => a.size - b.size);
                        break;
                    case 'size_desc':
                        sortedFiles.sort((a, b) => b.size - a.size);
                        break;
                    case 'name_asc':
                        sortedFiles.sort((a, b) => a.filename.localeCompare(b.filename));
                        break;
                    case 'name_desc':
                        sortedFiles.sort((a, b) => b.filename.localeCompare(a.filename));
                        break;
                    default:
                        sortedFiles.sort((a, b) => new Date(b.upload_time) - new Date(a.upload_time));
                }
                
                displayFiles(sortedFiles);
            }
            
            async function downloadFile(filename) {
                try {
                    window.open(`${API_BASE}/download/${encodeURIComponent(filename)}`, '_blank');
                } catch (error) {
                    showError('Download failed');
                    console.error('Download error:', error);
                }
            }
            
            async function lockFile(filename) {
                const password = prompt('Enter a password to lock this file (minimum 4 characters):');
                if (!password) return;
                
                if (password.length < 4) {
                    showError('Password must be at least 4 characters');
                    return;
                }
                
                try {
                    const response = await fetch(`${API_BASE}/lock/${encodeURIComponent(filename)}`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ password: password })
                    });
                    
                    if (response.ok) {
                        refreshFiles();
                        showSuccess('File locked successfully');
                    } else {
                        const result = await response.json();
                        showError(result.error || 'Failed to lock file');
                    }
                } catch (error) {
                    showError('Lock operation failed');
                    console.error('Lock error:', error);
                }
            }
            
            async function unlockFile(filename) {
                const password = prompt('Enter the password to unlock this file:');
                if (!password) return;
                
                try {
                    const response = await fetch(`${API_BASE}/unlock/${encodeURIComponent(filename)}`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ password: password })
                    });
                    
                    if (response.ok) {
                        refreshFiles();
                        showSuccess('File unlocked successfully');
                    } else {
                        const result = await response.json();
                        showError(result.error || 'Failed to unlock file');
                    }
                } catch (error) {
                    showError('Unlock operation failed');
                    console.error('Unlock error:', error);
                }
            }
            
            async function deleteFile(filename) {
                if (!confirm(`Are you sure you want to delete "${filename}"? This action cannot be undone.`)) {
                    return;
                }
                
                try {
                    const response = await fetch(`${API_BASE}/delete/${encodeURIComponent(filename)}`, {
                        method: 'DELETE'
                    });
                    
                    if (response.ok) {
                        refreshFiles();
                        showSuccess('File deleted successfully');
                    } else {
                        showError('Failed to delete file');
                    }
                } catch (error) {
                    showError('Delete operation failed');
                    console.error('Delete error:', error);
                }
            }
            
            function updateStats() {
                const totalFiles = currentFiles.length;
                const lockedFiles = currentFiles.filter(f => f.is_locked).length;
                const cloudFiles = currentFiles.filter(f => f.storage_type === 'cloud').length;
                
                document.getElementById('totalFiles').textContent = totalFiles;
                document.getElementById('lockedFiles').textContent = lockedFiles;
                document.getElementById('cloudFiles').textContent = cloudFiles;
            }
            
            function formatFileSize(bytes) {
                if (bytes === 0) return '0 B';
                const k = 1024;
                const sizes = ['B', 'KB', 'MB', 'GB'];
                const i = Math.floor(Math.log(bytes) / Math.log(k));
                return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
            }
            
            function formatDate(dateString) {
                const date = new Date(dateString);
                const now = new Date();
                const diffTime = Math.abs(now - date);
                const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
                
                if (diffDays === 1) return 'Today';
                if (diffDays === 2) return 'Yesterday';
                if (diffDays <= 7) return `${diffDays - 1} days ago`;
                
                return date.toLocaleDateString();
            }
            
            function escapeHtml(text) {
                const div = document.createElement('div');
                div.textContent = text;
                return div.innerHTML;
            }
            
            function showSuccess(message) {
                const statusDiv = document.getElementById('uploadStatus');
                statusDiv.innerHTML = `<div class="status success">✅ ${message}</div>`;
                setTimeout(() => {
                    statusDiv.innerHTML = '';
                }, 3000);
            }
            
            function showError(message) {
                const statusDiv = document.getElementById('uploadStatus');
                statusDiv.innerHTML = `<div class="status error">❌ ${message}</div>`;
                setTimeout(() => {
                    statusDiv.innerHTML = '';
                }, 5000);
            }
            
            // Auto-refresh files every 30 seconds
            setInterval(refreshFiles, 30000);
        </script>
    </body>
    </html>
    '''
    return html_template

@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        # Security checks
        if 'file' not in request.files:
            log_security_event('UPLOAD_ERROR', 'No file part in request')
            return jsonify({'error': 'No file part'}), 400
        
        file = request.files['file']
        if file.filename == '':
            log_security_event('UPLOAD_ERROR', 'No file selected')
            return jsonify({'error': 'No file selected'}), 400
        
        # Check file type
        if not allowed_file(file.filename):
            log_security_event('UPLOAD_ERROR', f'Invalid file type: {file.filename}')
            return jsonify({'error': 'File type not allowed'}), 400
        
        # Secure filename
        filename = secure_filename(file.filename)
        if not filename:
            log_security_event('UPLOAD_ERROR', 'Invalid filename')
            return jsonify({'error': 'Invalid filename'}), 400
        
        # Handle duplicate filenames
        counter = 1
        original_filename = filename
        while os.path.exists(os.path.join(UPLOAD_FOLDER, filename)):
            name, ext = os.path.splitext(original_filename)
            filename = f"{name}_{counter}{ext}"
            counter += 1
        
        file_size = 0
        storage_type = 'local'
        cloud_file_id = None
        
        # Check if file should be stored in cloud
        # Try to get file size from content_length or calculate it
        file_size_bytes = getattr(file, 'content_length', None)
        
        if file_size_bytes and file_size_bytes > CLOUD_STORAGE_THRESHOLD:
            # Use cloud storage for large files (when we know size upfront)
            cloud_storage = get_cloud_storage()
            if cloud_storage:
                # Save to temp file first
                temp_path = os.path.join(UPLOAD_FOLDER, f"temp_{filename}")
                file.save(temp_path)
                
                # Upload to cloud
                cloud_result = cloud_storage.upload_file(temp_path, filename)
                if cloud_result:
                    file_size = cloud_result['size']
                    cloud_file_id = cloud_result['id']
                    storage_type = 'cloud'
                    # Remove temp file
                    os.remove(temp_path)
                else:
                    # Fallback to local storage
                    filepath = os.path.join(UPLOAD_FOLDER, filename)
                    os.rename(temp_path, filepath)
                    file_size = os.path.getsize(filepath)
                    storage_type = 'local'
            else:
                # Cloud storage not available, use local
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                file.save(filepath)
                file_size = os.path.getsize(filepath)
                storage_type = 'local'
        else:
            # Use local storage for small files or when size is unknown
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            file_size = os.path.getsize(filepath)
            storage_type = 'local'
        
        # Save metadata
        metadata = {
            'original_name': file.filename,
            'size': file_size,
            'upload_time': datetime.now().isoformat(),
            'session_id': session['session_id'],
            'is_locked': False,
            'password_hash': None,
            'storage_type': storage_type,
            'cloud_file_id': cloud_file_id
        }
        save_file_metadata(filename, metadata)
        
        # Update session
        session['upload_count'] = session.get('upload_count', 0) + 1
        session['last_upload'] = time.time()
        
        # Log successful upload
        log_security_event('UPLOAD_SUCCESS', f'{filename} ({get_file_size(file_size)})')
        
        print(f"✅ File uploaded: {filename} ({get_file_size(file_size)})")
        
        return jsonify({
            'status': 'success',
            'filename': filename,
            'size': file_size,
            'session_id': session['session_id'],
            'is_locked': False
        }), 200
        
    except Exception as e:
        error_msg = f'Exception: {str(e)}'
        log_security_event('UPLOAD_ERROR', error_msg)
        print(f"❌ Upload error: {error_msg}")
        
        # Clean up any partial files
        try:
            if 'filepath' in locals() and os.path.exists(filepath):
                os.remove(filepath)
        except:
            pass
            
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

@app.route('/lock/<filename>', methods=['POST'])
def lock_file(filename):
    try:
        data = request.get_json()
        password = data.get('password')
        
        if not password or len(password) < 4:
            return jsonify({'error': 'Password must be at least 4 characters'}), 400
        
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404
        
        # Load metadata
        metadata = load_file_metadata(filename)
        if not metadata:
            return jsonify({'error': 'File metadata not found'}), 404
        
        # Check if user owns the file
        if metadata.get('session_id') != session.get('session_id'):
            log_security_event('LOCK_ERROR', f'Unauthorized lock attempt: {filename}')
            return jsonify({'error': 'You can only lock your own files'}), 403
        
        # Read and encrypt file
        with open(filepath, 'rb') as f:
            file_data = f.read()
        
        encrypted_data = encrypt_file(file_data, password)
        
        # Save encrypted file
        with open(filepath, 'wb') as f:
            f.write(encrypted_data)
        
        # Update metadata
        metadata['is_locked'] = True
        metadata['password_hash'] = hashlib.sha256(password.encode()).hexdigest()
        save_file_metadata(filename, metadata)
        
        log_security_event('LOCK_SUCCESS', filename)
        print(f"🔒 File locked: {filename}")
        
        return jsonify({
            'status': 'success',
            'message': 'File locked successfully'
        }), 200
        
    except Exception as e:
        log_security_event('LOCK_ERROR', f'Exception: {str(e)}')
        print(f"❌ Lock error: {str(e)}")
        return jsonify({'error': f'Lock failed: {str(e)}'}), 500

@app.route('/unlock/<filename>', methods=['POST'])
def unlock_file(filename):
    try:
        data = request.get_json()
        password = data.get('password')
        
        if not password:
            return jsonify({'error': 'Password required'}), 400
        
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404
        
        # Load metadata
        metadata = load_file_metadata(filename)
        if not metadata:
            return jsonify({'error': 'File metadata not found'}), 404
        
        # Check if file is locked
        if not metadata.get('is_locked'):
            return jsonify({'error': 'File is not locked'}), 400
        
        # Verify password
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        if metadata.get('password_hash') != password_hash:
            log_security_event('UNLOCK_ERROR', f'Wrong password for: {filename}')
            return jsonify({'error': 'Incorrect password'}), 401
        
        # Read and decrypt file
        with open(filepath, 'rb') as f:
            encrypted_data = f.read()
        
        try:
            decrypted_data = decrypt_file(encrypted_data, password)
        except ValueError as e:
            log_security_event('UNLOCK_ERROR', f'Decryption failed: {filename}')
            return jsonify({'error': 'Incorrect password or corrupted file'}), 401
        
        # Save decrypted file
        with open(filepath, 'wb') as f:
            f.write(decrypted_data)
        
        # Update metadata
        metadata['is_locked'] = False
        metadata['password_hash'] = None
        save_file_metadata(filename, metadata)
        
        log_security_event('UNLOCK_SUCCESS', filename)
        print(f"🔓 File unlocked: {filename}")
        
        return jsonify({
            'status': 'success',
            'message': 'File unlocked successfully'
        }), 200
        
    except Exception as e:
        log_security_event('UNLOCK_ERROR', f'Exception: {str(e)}')
        print(f"❌ Unlock error: {str(e)}")
        return jsonify({'error': f'Unlock failed: {str(e)}'}), 500

@app.route('/files')
def list_files():
    try:
        files = []
        for filename in os.listdir(UPLOAD_FOLDER):
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.isfile(filepath) and not filename.endswith('.meta'):
                metadata = load_file_metadata(filename)
                file_info = {
                    'filename': filename,
                    'name': filename,
                    'size': os.path.getsize(filepath),
                    'upload_time': metadata.get('upload_time', datetime.now().isoformat()) if metadata else datetime.now().isoformat(),
                    'is_locked': metadata.get('is_locked', False) if metadata else False,
                    'is_owner': metadata.get('session_id') == session.get('session_id') if metadata else False,
                    'storage_type': metadata.get('storage_type', 'local') if metadata else 'local'
                }
                files.append(file_info)
        
        # Sort by upload time (newest first) by default
        files.sort(key=lambda x: x['upload_time'], reverse=True)
        return jsonify(files)
        
    except Exception as e:
        log_security_event('LIST_ERROR', f'Exception: {str(e)}')
        print(f"❌ List files error: {str(e)}")
        return jsonify({'error': 'Failed to list files'}), 500

@app.route('/download/<filename>')
def download_file(filename):
    try:
        # Load metadata
        metadata = load_file_metadata(filename)
        if not metadata:
            log_security_event('DOWNLOAD_ERROR', f'File not found: {filename}')
            return jsonify({'error': 'File not found'}), 404
        
        # Check if file is locked
        if metadata.get('is_locked'):
            return jsonify({'error': 'File is locked. Please unlock it first.'}), 403
        
        storage_type = metadata.get('storage_type', 'local')
        
        if storage_type == 'cloud':
            # Download from cloud storage
            cloud_storage = get_cloud_storage()
            if not cloud_storage:
                return jsonify({'error': 'Cloud storage not available'}), 500
            
            cloud_file_id = metadata.get('cloud_file_id')
            if not cloud_file_id:
                return jsonify({'error': 'Cloud file ID not found'}), 404
            
            # Download from cloud
            cloud_result = cloud_storage.download_file(cloud_file_id)
            if not cloud_result:
                return jsonify({'error': 'Failed to download from cloud'}), 500
            
            # Create temporary file
            temp_path = os.path.join(UPLOAD_FOLDER, f"temp_download_{filename}")
            with open(temp_path, 'wb') as f:
                f.write(cloud_result['content'])
            
            log_security_event('DOWNLOAD_SUCCESS', f'{filename} (cloud)')
            print(f"📥 File downloaded from cloud: {filename}")
            
            # Return file and clean up after sending
            response = send_file(temp_path, as_attachment=True, download_name=filename)
            
            # Clean up temp file after response
            def cleanup():
                try:
                    os.remove(temp_path)
                except:
                    pass
            
            response.call_on_close(cleanup)
            return response
            
        else:
            # Local file download
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            if not os.path.exists(filepath) or not os.path.isfile(filepath):
                log_security_event('DOWNLOAD_ERROR', f'File not found: {filename}')
                return jsonify({'error': 'File not found'}), 404
            
            log_security_event('DOWNLOAD_SUCCESS', filename)
            print(f"📥 File downloaded: {filename}")
            return send_file(filepath, as_attachment=True, download_name=filename)
        
    except Exception as e:
        log_security_event('DOWNLOAD_ERROR', f'Exception: {str(e)}')
        print(f"❌ Download error: {str(e)}")
        return jsonify({'error': 'Download failed'}), 500

@app.route('/delete/<filename>', methods=['DELETE'])
def delete_file(filename):
    try:
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        if not os.path.exists(filepath) or not os.path.isfile(filepath):
            log_security_event('DELETE_ERROR', f'File not found: {filename}')
            return jsonify({'error': 'File not found'}), 404
        
        # Load metadata
        metadata = load_file_metadata(filename)
        if not metadata:
            log_security_event('DELETE_ERROR', f'File metadata not found: {filename}')
            return jsonify({'error': 'File metadata not found'}), 404
        
        # Check if user owns the file (allow deletion if session matches or if no session exists)
        file_session_id = metadata.get('session_id')
        current_session_id = session.get('session_id')
        
        # Allow deletion if:
        # 1. Session IDs match, OR
        # 2. File has no session ID (orphaned files), OR  
        # 3. Current session is empty (new user)
        if file_session_id and current_session_id and file_session_id != current_session_id:
            log_security_event('DELETE_ERROR', f'Unauthorized delete attempt: {filename}')
            return jsonify({'error': 'You can only delete your own files'}), 403
        
        # Check if file is locked and requires password
        if metadata.get('is_locked'):
            data = request.get_json()
            password = data.get('password') if data else None
            
            if not password:
                log_security_event('DELETE_ERROR', f'Password required for locked file: {filename}')
                return jsonify({'error': 'Password required to delete locked file'}), 401
            
            # Verify password
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            if metadata.get('password_hash') != password_hash:
                log_security_event('DELETE_ERROR', f'Wrong password for locked file: {filename}')
                return jsonify({'error': 'Incorrect password'}), 401
        
        # Delete file based on storage type
        storage_type = metadata.get('storage_type', 'local')
        
        if storage_type == 'cloud':
            # Delete from cloud storage
            cloud_storage = get_cloud_storage()
            if cloud_storage:
                cloud_file_id = metadata.get('cloud_file_id')
                if cloud_file_id:
                    cloud_storage.delete_file(cloud_file_id)
        else:
            # Delete local file
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.exists(filepath):
                os.remove(filepath)
        
        # Remove metadata file
        meta_file = os.path.join(UPLOAD_FOLDER, f"{filename}.meta")
        if os.path.exists(meta_file):
            os.remove(meta_file)
        
        log_security_event('DELETE_SUCCESS', filename)
        print(f"🗑️ File deleted: {filename}")
        return jsonify({'status': 'success', 'message': 'File deleted successfully'})
        
    except Exception as e:
        log_security_event('DELETE_ERROR', f'Exception: {str(e)}')
        print(f"❌ Delete error: {str(e)}")
        return jsonify({'error': 'Delete failed'}), 500

# Ultra High-Speed Upload API Endpoints
@app.route('/api/upload/session', methods=['POST'])
def create_upload_session():
    """Create a new upload session for chunked uploads"""
    if not ULTRA_UPLOAD_AVAILABLE:
        return jsonify({'error': 'Ultra upload system not available'}), 503
    
    try:
        data = request.get_json()
        if not data or 'filename' not in data or 'total_size' not in data:
            return jsonify({'error': 'Missing filename or total_size'}), 400
        
        filename = data['filename']
        total_size = int(data['total_size'])
        
        # Validate file size
        if total_size > MAX_FILE_SIZE_PER_UPLOAD:
            return jsonify({'error': f'File size exceeds maximum limit of {get_file_size(MAX_FILE_SIZE_PER_UPLOAD)}'}), 400
        
        # Validate file type
        if not allowed_file(filename):
            return jsonify({'error': 'File type not allowed'}), 400
        
        # Create upload session
        session_id = upload_manager.create_upload_session(filename, total_size)
        
        log_security_event('UPLOAD_SESSION_CREATED', f'{filename} ({get_file_size(total_size)})')
        
        return jsonify({
            'status': 'success',
            'session_id': session_id,
            'filename': filename,
            'total_size': total_size,
            'chunk_size': upload_manager.chunk_size,
            'total_chunks': (total_size + upload_manager.chunk_size - 1) // upload_manager.chunk_size
        }), 200
        
    except Exception as e:
        log_security_event('UPLOAD_SESSION_ERROR', f'Exception: {str(e)}')
        return jsonify({'error': f'Session creation failed: {str(e)}'}), 500

@app.route('/api/upload/chunk', methods=['POST'])
def upload_chunk():
    """Upload a single chunk of a file"""
    if not ULTRA_UPLOAD_AVAILABLE:
        return jsonify({'error': 'Ultra upload system not available'}), 503
    
    try:
        if 'chunk' not in request.files:
            return jsonify({'error': 'No chunk file provided'}), 400
        
        if 'session_id' not in request.form:
            return jsonify({'error': 'No session ID provided'}), 400
        
        if 'chunk_id' not in request.form:
            return jsonify({'error': 'No chunk ID provided'}), 400
        
        chunk_file = request.files['chunk']
        session_id = request.form['session_id']
        chunk_id = int(request.form['chunk_id'])
        
        # Read chunk data
        chunk_data = chunk_file.read()
        
        # Upload chunk
        result = upload_manager.upload_chunk(session_id, chunk_id, chunk_data)
        
        if 'error' in result:
            log_security_event('CHUNK_UPLOAD_ERROR', f'Session: {session_id}, Chunk: {chunk_id}, Error: {result["error"]}')
            return jsonify(result), 400
        
        log_security_event('CHUNK_UPLOAD_SUCCESS', f'Session: {session_id}, Chunk: {chunk_id}')
        
        return jsonify(result), 200
        
    except Exception as e:
        log_security_event('CHUNK_UPLOAD_ERROR', f'Exception: {str(e)}')
        return jsonify({'error': f'Chunk upload failed: {str(e)}'}), 500

@app.route('/api/upload/progress/<session_id>')
def get_upload_progress(session_id):
    """Get upload progress for a session"""
    if not ULTRA_UPLOAD_AVAILABLE:
        return jsonify({'error': 'Ultra upload system not available'}), 503
    
    try:
        progress = upload_manager.get_upload_progress(session_id)
        
        if 'error' in progress:
            return jsonify(progress), 404
        
        return jsonify(progress), 200
        
    except Exception as e:
        return jsonify({'error': f'Progress retrieval failed: {str(e)}'}), 500

@app.route('/api/upload/assemble', methods=['POST'])
def assemble_file():
    """Assemble uploaded chunks into final file"""
    if not ULTRA_UPLOAD_AVAILABLE:
        return jsonify({'error': 'Ultra upload system not available'}), 503
    
    try:
        data = request.get_json()
        if not data or 'session_id' not in data:
            return jsonify({'error': 'Missing session ID'}), 400
        
        session_id = data['session_id']
        
        # Get session info
        progress = upload_manager.get_upload_progress(session_id)
        if 'error' in progress:
            return jsonify({'error': 'Session not found'}), 404
        
        # Determine output path
        filename = progress['filename']
        secure_filename_safe = secure_filename(filename)
        
        # Handle duplicate filenames
        counter = 1
        original_filename = secure_filename_safe
        while os.path.exists(os.path.join(UPLOAD_FOLDER, secure_filename_safe)):
            name, ext = os.path.splitext(original_filename)
            secure_filename_safe = f"{name}_{counter}{ext}"
            counter += 1
        
        output_path = os.path.join(UPLOAD_FOLDER, secure_filename_safe)
        
        # Assemble file
        result = upload_manager.assemble_file(session_id, output_path)
        
        if 'error' in result:
            log_security_event('FILE_ASSEMBLY_ERROR', f'Session: {session_id}, Error: {result["error"]}')
            return jsonify(result), 500
        
        # Save metadata
        metadata = {
            'original_name': filename,
            'size': result['final_size'],
            'upload_time': datetime.now().isoformat(),
            'session_id': session_id,
            'is_locked': False,
            'password_hash': None,
            'storage_type': 'local',
            'cloud_file_id': None,
            'upload_method': 'ultra_chunked'
        }
        save_file_metadata(secure_filename_safe, metadata)
        
        # Clean up session
        upload_manager.cleanup_session(session_id)
        
        log_security_event('FILE_ASSEMBLY_SUCCESS', f'{filename} ({get_file_size(result["final_size"])})')
        
        return jsonify({
            'status': 'success',
            'filename': secure_filename_safe,
            'original_name': filename,
            'final_size': result['final_size'],
            'output_path': output_path
        }), 200
        
    except Exception as e:
        log_security_event('FILE_ASSEMBLY_ERROR', f'Exception: {str(e)}')
        return jsonify({'error': f'File assembly failed: {str(e)}'}), 500

@app.route('/api/upload/sessions')
def list_upload_sessions():
    """List all active upload sessions"""
    if not ULTRA_UPLOAD_AVAILABLE:
        return jsonify({'error': 'Ultra upload system not available'}), 503
    
    try:
        sessions = upload_manager.get_active_sessions()
        return jsonify({
            'status': 'success',
            'sessions': sessions,
            'total_sessions': len(sessions)
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'Session listing failed: {str(e)}'}), 500

@app.route('/ultra-upload')
def ultra_upload_page():
    """Serve the ultra-high-speed upload interface"""
    try:
        with open('ultra_upload_frontend.html', 'r') as f:
            html_content = f.read()
        return html_content
    except FileNotFoundError:
        return jsonify({'error': 'Ultra upload interface not found'}), 404

@app.route('/health')
def health_check():
    try:
        uploads_ok = os.path.exists(UPLOAD_FOLDER)
        
        health_status = {
            'status': 'healthy' if uploads_ok else 'unhealthy',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'version': '2.1.0',
            'service': 'B-Transfer by Balsim Technologies',
            'copyright': 'Copyright (c) 2025 Balsim Technologies. All rights reserved.',
            'features': ['file_locking', 'military_grade_encryption', 'rate_limiting'],
            'checks': {
                'uploads_directory': uploads_ok
            }
        }
        
        return jsonify(health_status), 200 if health_status['status'] == 'healthy' else 503
        
    except Exception as e:
        print(f"❌ Health check error: {str(e)}")
        return jsonify({'error': 'Health check failed'}), 500

@app.route('/favicon.ico')
def favicon():
    return send_from_directory('.', 'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/apple-touch-icon.png')
def apple_touch_icon():
    return send_from_directory('.', 'apple-touch-icon.png', mimetype='image/png')

@app.route('/apple-touch-icon-precomposed.png')
def apple_touch_icon_precomposed():
    return send_from_directory('.', 'apple-touch-icon-precomposed.png', mimetype='image/png')

if __name__ == '__main__':
    def get_local_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
    
    port = int(os.environ.get('PORT', 8081))
    
    # Check if running on cloud platforms
    if os.environ.get('RAILWAY_ENVIRONMENT') == 'production':
        print("🚂 B-Transfer Server Starting on Railway...")
        print("=" * 60)
        print("Copyright (c) 2025 Balsim Technologies. All rights reserved.")
        print("Proprietary and confidential software.")
        print("=" * 60)
        print("☁️ Cloud deployment with Google Cloud Storage integration")
        print("🔄 Server supports up to 5GB file transfers")
        print("🔐 Enhanced security with rate limiting")
        print("🔒 Military-grade file locking with AES-256")
        print("🕐 Auto-delete after 24 hours")
        print("=" * 60)
        print("Press Ctrl+C to stop the server")
        print("")
        
        # Railway production settings
        app.config['PREFERRED_URL_SCHEME'] = 'https'
        app.run(host='0.0.0.0', port=port, threaded=True, debug=False)
        
    elif os.environ.get('RENDER'):
        print("☁️ B-Transfer Server Starting on Render...")
        print("=" * 60)
        print("Copyright (c) 2025 Balsim Technologies. All rights reserved.")
        print("Proprietary and confidential software.")
        print("=" * 60)
        print("☁️ Cloud deployment with Google Cloud Storage integration")
        print("🔄 Server supports up to 5GB file transfers")
        print("🔐 Enhanced security with rate limiting")
        print("🔒 Military-grade file locking with AES-256")
        print("🕐 Auto-delete after 24 hours")
        print("=" * 60)
        print("Press Ctrl+C to stop the server")
        print("")
        
        # Render production settings
        app.config['PREFERRED_URL_SCHEME'] = 'https'
        app.run(host='0.0.0.0', port=port, threaded=True, debug=False)
        
    else:
        # Local development
        local_ip = get_local_ip()
        
        print("🚀 B-Transfer Server Starting...")
        print("=" * 60)
        print("Copyright (c) 2025 Balsim Technologies. All rights reserved.")
        print("Proprietary and confidential software.")
        print("=" * 60)
        print(f"📱 Access from your phone: http://{local_ip}:{port}")
        print(f"💻 Access from this computer: http://localhost:{port}")
        print("=" * 60)
        print("📁 Files saved in 'uploads' folder and Google Drive")
        print("🔄 Server supports up to 5GB file transfers")
        print("☁️ Large files (>100MB) stored in Google Cloud Storage")
        print("🔐 Enhanced security with rate limiting")
        print("🔒 Military-grade file locking with AES-256")
        print("🕐 Auto-delete after 24 hours")
        print("=" * 60)
        print("Press Ctrl+C to stop the server")
        print("")
        
        app.run(host='0.0.0.0', port=port, threaded=True, debug=False) 