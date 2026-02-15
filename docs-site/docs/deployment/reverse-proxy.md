# Reverse Proxy

A reverse proxy sits in front of Pipelit to handle HTTPS termination, WebSocket upgrades, and optional domain-based routing. This page provides configurations for Nginx and Caddy.

## Key Requirements

Pipelit uses both standard HTTP and WebSocket connections, so your reverse proxy must:

1. **Proxy HTTP requests** to the FastAPI backend (default port 8000)
2. **Upgrade WebSocket connections** at the `/ws/` path
3. **Terminate TLS/SSL** with a valid certificate
4. **Pass client IP headers** for logging and rate limiting

## Nginx

### Basic Configuration

```nginx title="/etc/nginx/sites-available/pipelit"
upstream pipelit_backend {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name your-domain.com;

    # Redirect HTTP to HTTPS
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # SSL certificates (Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Max upload size (for file uploads, webhook payloads)
    client_max_body_size 50M;

    # Proxy all requests to FastAPI
    location / {
        proxy_pass http://pipelit_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket endpoint
    location /ws/ {
        proxy_pass http://pipelit_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket timeouts
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}
```

### Enable the Site

```bash
sudo ln -s /etc/nginx/sites-available/pipelit /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

!!! tip "WebSocket timeouts"
    The `proxy_read_timeout` and `proxy_send_timeout` values are set to 24 hours (86400 seconds) for the WebSocket endpoint. Pipelit's WebSocket uses a 30-second ping/pong heartbeat to keep the connection alive, but Nginx's default 60-second timeout can still close idle connections prematurely.

## Caddy

Caddy is a simpler alternative that automatically handles HTTPS certificate issuance and renewal via Let's Encrypt.

### Caddyfile

```caddyfile title="/etc/caddy/Caddyfile"
your-domain.com {
    reverse_proxy localhost:8000
}
```

That is the complete Caddy configuration. Caddy automatically:

- Obtains and renews Let's Encrypt certificates
- Redirects HTTP to HTTPS
- Handles WebSocket upgrade headers
- Sets appropriate proxy headers

### Start Caddy

```bash
sudo systemctl enable caddy
sudo systemctl start caddy
```

!!! note "Caddy and WebSocket"
    Caddy natively supports WebSocket proxying with no additional configuration. The `reverse_proxy` directive handles HTTP upgrade headers transparently.

## SSL/TLS with Let's Encrypt

### Using Certbot (for Nginx)

```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx

# Obtain a certificate
sudo certbot --nginx -d your-domain.com

# Verify auto-renewal
sudo certbot renew --dry-run
```

Certbot automatically modifies your Nginx configuration to include the SSL certificate paths and enables auto-renewal via a systemd timer.

### Using Caddy

Caddy handles certificate management automatically. No additional setup is needed. Ensure that:

- Port 80 and 443 are open on your firewall
- DNS A/AAAA records point to your server's IP address

## Firewall Configuration

After setting up the reverse proxy, block direct access to the backend port:

```bash
# Allow only HTTPS and HTTP (for redirect)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Block direct backend access from external networks
# (port 8000 should only be accessible from localhost)
sudo ufw deny 8000/tcp

# Block Redis from external access
sudo ufw deny 6379/tcp
```

## Verifying WebSocket Connectivity

After configuring the reverse proxy, verify that WebSocket connections work:

```bash
# Using websocat (install: cargo install websocat)
websocat wss://your-domain.com/ws/?token=your-api-key

# Or use the browser's developer tools:
# 1. Open your Pipelit instance
# 2. Open DevTools -> Network -> WS tab
# 3. You should see a WebSocket connection to /ws/
```

A successful connection will show periodic `ping`/`pong` messages every 30 seconds.
