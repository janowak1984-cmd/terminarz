from flask import request

def get_client_ip():
    """
    DEV:
      127.0.0.1

    PROD (Railway / Nginx / Cloudflare):
      X-Forwarded-For
    """

    # Proxy / load balancer
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()

    return request.remote_addr
