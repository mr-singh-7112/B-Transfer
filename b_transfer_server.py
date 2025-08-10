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
from flask import Flask, request, jsonify, send_file, session, render_template_string
from werkzeug.utils import secure_filename
import socket
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from cloud_storage import get_cloud_storage

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)  # Secure session key
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1024  # 10GB limit
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)

# Setup upload directory
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Security settings
MAX_UPLOADS_PER_SESSION = 50
MAX_FILE_SIZE_PER_UPLOAD = 5 * 1024 * 1024 * 1024  # 5GB
CLOUD_STORAGE_THRESHOLD = 100 * 1024 * 1024  # 100MB - use cloud for files > 100MB
ALLOWED_EXTENSIONS = {
    'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'mp4', 'avi', 'mov', 'mp3', 'wav',
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
        if session.get('last_upload') and current_time - session['last_upload'] < 1:
            log_security_event('RATE_LIMIT', f'Too many uploads from {get_client_ip()}')
            return jsonify({'error': 'Rate limit exceeded. Please wait before uploading again.'}), 429
        
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
        <title>B-Transfer - Secure File Transfer</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                color: #333;
            }
            
            .container {
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
            }
            
            .header {
                text-align: center;
                margin-bottom: 40px;
                color: white;
            }
            
            .header h1 {
                font-size: 3rem;
                margin-bottom: 10px;
                text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
            }
            
            .header p {
                font-size: 1.2rem;
                opacity: 0.9;
            }
            
            .main-content {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 30px;
                margin-bottom: 40px;
            }
            
            .card {
                background: white;
                border-radius: 15px;
                padding: 30px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                transition: transform 0.3s ease;
            }
            
            .card:hover {
                transform: translateY(-5px);
            }
            
            .card h3 {
                color: #667eea;
                margin-bottom: 20px;
                font-size: 1.5rem;
                border-bottom: 2px solid #667eea;
                padding-bottom: 10px;
            }
            
            .upload-area {
                border: 3px dashed #667eea;
                border-radius: 10px;
                padding: 40px;
                text-align: center;
                margin-bottom: 20px;
                transition: all 0.3s ease;
                cursor: pointer;
            }
            
            .upload-area:hover {
                border-color: #764ba2;
                background: #f8f9ff;
            }
            
            .upload-area.dragover {
                border-color: #764ba2;
                background: #f0f2ff;
                transform: scale(1.02);
            }
            
            .file-input {
                display: none;
            }
            
            .upload-btn {
                background: linear-gradient(45deg, #667eea, #764ba2);
                color: white;
                border: none;
                padding: 15px 30px;
                border-radius: 25px;
                font-size: 1.1rem;
                cursor: pointer;
                transition: all 0.3s ease;
                margin: 10px;
            }
            
            .upload-btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 5px 15px rgba(0,0,0,0.2);
            }
            
            .files-list {
                max-height: 400px;
                overflow-y: auto;
            }
            
            .file-item {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 15px;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                margin-bottom: 10px;
                background: #f8f9fa;
                transition: all 0.3s ease;
            }
            
            .file-item:hover {
                background: #e9ecef;
                border-color: #667eea;
            }
            
            .file-info {
                flex: 1;
            }
            
            .file-name {
                font-weight: bold;
                color: #333;
                margin-bottom: 5px;
            }
            
            .file-meta {
                font-size: 0.9rem;
                color: #666;
            }
            
            .file-actions {
                display: flex;
                gap: 10px;
            }
            
            .action-btn {
                padding: 8px 15px;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                font-size: 0.9rem;
                transition: all 0.3s ease;
            }
            
            .download-btn {
                background: #28a745;
                color: white;
            }
            
            .download-btn:hover {
                background: #218838;
            }
            
            .lock-btn {
                background: #ffc107;
                color: #212529;
            }
            
            .lock-btn:hover {
                background: #e0a800;
            }
            
            .unlock-btn {
                background: #17a2b8;
                color: white;
            }
            
            .unlock-btn:hover {
                background: #138496;
            }
            
            .delete-btn {
                background: #dc3545;
                color: white;
            }
            
            .delete-btn:hover {
                background: #c82333;
            }
            
            .status {
                padding: 10px;
                border-radius: 5px;
                margin: 10px 0;
                text-align: center;
            }
            
            .status.success {
                background: #d4edda;
                color: #155724;
                border: 1px solid #c3e6cb;
            }
            
            .status.error {
                background: #f8d7da;
                color: #721c24;
                border: 1px solid #f5c6cb;
            }
            
            .progress-bar {
                width: 100%;
                height: 20px;
                background: #e9ecef;
                border-radius: 10px;
                overflow: hidden;
                margin: 10px 0;
            }
            
            .progress-fill {
                height: 100%;
                background: linear-gradient(45deg, #667eea, #764ba2);
                width: 0%;
                transition: width 0.3s ease;
            }
            
            .footer {
                text-align: center;
                color: white;
                margin-top: 40px;
                opacity: 0.8;
            }
            
            @media (max-width: 768px) {
                .main-content {
                    grid-template-columns: 1fr;
                }
                
                .header h1 {
                    font-size: 2rem;
                }
                
                .container {
                    padding: 10px;
                }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🚀 B-Transfer</h1>
                <p>Secure File Transfer with Military-Grade Encryption</p>
            </div>
            
            <div class="main-content">
                <div class="card">
                    <h3>📤 Upload Files</h3>
                    <div class="upload-area" id="uploadArea">
                        <p>📁 Drag & drop files here or click to browse</p>
                        <input type="file" id="fileInput" class="file-input" multiple>
                        <button class="upload-btn" onclick="document.getElementById('fileInput').click()">
                            Choose Files
                        </button>
                    </div>
                    <div id="uploadStatus"></div>
                    <div class="progress-bar" id="progressBar" style="display: none;">
                        <div class="progress-fill" id="progressFill"></div>
                    </div>
                </div>
                
                <div class="card">
                    <h3>📋 File Management</h3>
                    <button class="upload-btn" onclick="refreshFiles()">🔄 Refresh Files</button>
                    <div id="filesList" class="files-list"></div>
                </div>
            </div>
            
            <div class="footer">
                <p>© 2025 Balsim Technologies. All rights reserved.</p>
                <p>Proprietary and confidential software.</p>
            </div>
        </div>

        <script>
            const API_BASE = window.location.origin;
            let currentFiles = [];
            
            // Drag and drop functionality
            const uploadArea = document.getElementById('uploadArea');
            const fileInput = document.getElementById('fileInput');
            
            uploadArea.addEventListener('dragover', (e) => {
                e.preventDefault();
                uploadArea.classList.add('dragover');
            });
            
            uploadArea.addEventListener('dragleave', () => {
                uploadArea.classList.remove('dragover');
            });
            
            uploadArea.addEventListener('drop', (e) => {
                e.preventDefault();
                uploadArea.classList.remove('dragover');
                const files = e.dataTransfer.files;
                handleFiles(files);
            });
            
            fileInput.addEventListener('change', (e) => {
                handleFiles(e.target.files);
            });
            
            function handleFiles(files) {
                Array.from(files).forEach(file => {
                    uploadFile(file);
                });
            }
            
            async function uploadFile(file) {
                const formData = new FormData();
                formData.append('file', file);
                
                const statusDiv = document.getElementById('uploadStatus');
                statusDiv.innerHTML = `<div class="status">📤 Uploading ${file.name}...</div>`;
                
                const progressBar = document.getElementById('progressBar');
                const progressFill = document.getElementById('progressFill');
                progressBar.style.display = 'block';
                
                try {
                    const response = await fetch(`${API_BASE}/upload`, {
                        method: 'POST',
                        body: formData
                    });
                    
                    const result = await response.json();
                    
                    if (response.ok) {
                        statusDiv.innerHTML = `<div class="status success">✅ ${file.name} uploaded successfully!</div>`;
                        refreshFiles();
                    } else {
                        statusDiv.innerHTML = `<div class="status error">❌ Error: ${result.error}</div>`;
                    }
                } catch (error) {
                    statusDiv.innerHTML = `<div class="status error">❌ Upload failed: ${error.message}</div>`;
                }
                
                progressBar.style.display = 'none';
                setTimeout(() => {
                    statusDiv.innerHTML = '';
                }, 5000);
            }
            
            async function refreshFiles() {
                try {
                    const response = await fetch(`${API_BASE}/files`);
                    const files = await response.json();
                    currentFiles = files;
                    displayFiles(files);
                } catch (error) {
                    console.error('Error fetching files:', error);
                }
            }
            
            function displayFiles(files) {
                const filesList = document.getElementById('filesList');
                
                if (files.length === 0) {
                    filesList.innerHTML = '<p style="text-align: center; color: #666;">No files uploaded yet.</p>';
                    return;
                }
                
                filesList.innerHTML = files.map(file => `
                    <div class="file-item">
                        <div class="file-info">
                            <div class="file-name">${file.filename}</div>
                            <div class="file-meta">
                                📏 ${formatFileSize(file.size)} | 
                                📅 ${new Date(file.upload_time).toLocaleString()} |
                                ${file.is_locked ? '🔒 Locked' : '🔓 Unlocked'}
                            </div>
                        </div>
                        <div class="file-actions">
                            <button class="action-btn download-btn" onclick="downloadFile('${file.filename}')">
                                📥 Download
                            </button>
                            ${file.is_locked ? 
                                `<button class="action-btn unlock-btn" onclick="unlockFile('${file.filename}')">🔓 Unlock</button>` :
                                `<button class="action-btn lock-btn" onclick="lockFile('${file.filename}')">🔒 Lock</button>`
                            }
                            <button class="action-btn delete-btn" onclick="deleteFile('${file.filename}')">
                                🗑️ Delete
                            </button>
                        </div>
                    </div>
                `).join('');
            }
            
            async function downloadFile(filename) {
                try {
                    window.open(`${API_BASE}/download/${filename}`, '_blank');
                } catch (error) {
                    console.error('Download error:', error);
                }
            }
            
            async function lockFile(filename) {
                try {
                    const response = await fetch(`${API_BASE}/lock/${filename}`, {
                        method: 'POST'
                    });
                    
                    if (response.ok) {
                        refreshFiles();
                    }
                } catch (error) {
                    console.error('Lock error:', error);
                }
            }
            
            async function unlockFile(filename) {
                try {
                    const response = await fetch(`${API_BASE}/unlock/${filename}`, {
                        method: 'POST'
                    });
                    
                    if (response.ok) {
                        refreshFiles();
                    }
                } catch (error) {
                    console.error('Unlock error:', error);
                }
            }
            
            async function deleteFile(filename) {
                if (!confirm(`Are you sure you want to delete ${filename}?`)) {
                    return;
                }
                
                try {
                    const response = await fetch(`${API_BASE}/delete/${filename}`, {
                        method: 'DELETE'
                    });
                    
                    if (response.ok) {
                        refreshFiles();
                    }
                } catch (error) {
                    console.error('Delete error:', error);
                }
            }
            
            function formatFileSize(bytes) {
                if (bytes === 0) return '0 Bytes';
                const k = 1024;
                const sizes = ['Bytes', 'KB', 'MB', 'GB'];
                const i = Math.floor(Math.log(bytes) / Math.log(k));
                return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
            }
            
            // Auto-refresh files every 30 seconds
            setInterval(refreshFiles, 30000);
            
            // Load files on page load
            window.onload = function() {
                refreshFiles();
            };
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
        if file.content_length and file.content_length > CLOUD_STORAGE_THRESHOLD:
            # Use cloud storage for large files
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
            # Use local storage for small files
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
        log_security_event('UPLOAD_ERROR', f'Exception: {str(e)}')
        print(f"❌ Upload error: {str(e)}")
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
                    'name': filename,
                    'size': os.path.getsize(filepath),
                    'is_locked': metadata.get('is_locked', False) if metadata else False,
                    'is_owner': metadata.get('session_id') == session.get('session_id') if metadata else False
                }
                files.append(file_info)
        
        files.sort(key=lambda x: x['name'])
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
        
        # Check if user owns the file
        if metadata.get('session_id') != session.get('session_id'):
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