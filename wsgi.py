#!/usr/bin/env python3
"""
WSGI entry point for B-Transfer
This file allows Gunicorn to properly import the Flask app
"""

from b_transfer_server import app

if __name__ == "__main__":
    app.run() 