# Gunicorn configuration for B-Transfer
bind = "0.0.0.0:$PORT"
workers = 4
worker_class = "eventlet"
timeout = 300
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
worker_connections = 1000
preload_app = True 