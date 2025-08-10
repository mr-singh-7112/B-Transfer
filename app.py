#!/usr/bin/env python3
"""
Fallback app.py for Render deployment
This file redirects to our main application
"""

import os
import sys

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from b_transfer_server import app
    print("✅ Successfully imported Flask app from b_transfer_server")
except ImportError as e:
    print(f"❌ Error importing Flask app: {e}")
    print(f"Current working directory: {os.getcwd()}")
    print(f"Python path: {sys.path}")
    sys.exit(1)

# This is what Render expects by default
application = app 