#!/bin/bash

# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install Python and dependencies
sudo apt-get install -y python3.12 python3.12-venv python3.12-dev
sudo apt-get install -y nginx openssl

# Create application directory
sudo mkdir -p /var/www/litchain
sudo chown ubuntu:ubuntu /var/www/litchain

# Clone repository (replace with your actual repository)
git clone https://github.com/your-repo/litchain.git /var/www/litchain

# Set up Python virtual environment
cd /var/www/litchain
python3.12 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Generate self-signed SSL certificate
sudo mkdir -p /etc/nginx/ssl
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/nginx/ssl/litchain.key \
    -out /etc/nginx/ssl/litchain.crt \
    -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost"

# Set up Nginx configuration with SSL
sudo tee /etc/nginx/sites-available/litchain << EOF
server {
    listen 80;
    server_name localhost;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl;
    server_name localhost;

    ssl_certificate /etc/nginx/ssl/litchain.crt;
    ssl_certificate_key /etc/nginx/ssl/litchain.key;
    
    # SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_cache_bypass \$http_upgrade;
    }
}
EOF

# Enable the site
sudo ln -s /etc/nginx/sites-available/litchain /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default

# Create systemd service
sudo tee /etc/systemd/system/litchain.service << EOF
[Unit]
Description=LitChain Application
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/var/www/litchain
Environment="PATH=/var/www/litchain/venv/bin"
Environment="CHAINLIT_URL=https://localhost"
ExecStart=/var/www/litchain/venv/bin/chainlit run app.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Start services
sudo systemctl daemon-reload
sudo systemctl start litchain
sudo systemctl enable litchain
sudo systemctl restart nginx 