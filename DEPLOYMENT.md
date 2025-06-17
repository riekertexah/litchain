# LitChain Deployment Guide

## Prerequisites
1. AWS EC2 instance running Ubuntu
2. Domain name (optional for production)
3. AWS Route 53 (optional for production)
4. AWS RDS or other database service (for data layer)

## Deployment Steps

### 1. EC2 Setup
1. Connect to your EC2 instance:
```bash
ssh -i your-key.pem ubuntu@your-ec2-ip
```

2. Make the deployment script executable:
```bash
chmod +x deploy.sh
```

3. Update the following in deploy.sh:
   - Update the git repository URL
   - Adjust Python version if needed
   - (Optional) Update SSL certificate details in the OpenSSL command

4. Run the deployment script:
```bash
./deploy.sh
```

### 2. SSL Certificate (Self-Signed)
The deployment script automatically:
1. Generates a self-signed SSL certificate valid for 365 days
2. Configures Nginx to use the certificate
3. Sets up HTTP to HTTPS redirect

To access the application:
1. Use `https://localhost` or your EC2 public IP
2. Accept the security warning in your browser (this is normal for self-signed certificates)

To bypass security warnings in different browsers:
- **Chrome**: Click "Advanced" -> "Proceed to localhost (unsafe)"
- **Firefox**: Click "Advanced" -> "Accept the Risk and Continue"
- **Safari**: Click "Show Details" -> "visit this website"

### 3. Data Layer Setup
1. Create an RDS instance or other database service
2. Update environment variables in the systemd service:
```bash
sudo nano /etc/systemd/system/litchain.service
```
Add your database connection string:
```
Environment="DATABASE_URL=your-connection-string"
```

3. Restart the service:
```bash
sudo systemctl restart litchain
```

### 4. Monitoring
1. Check application logs:
```bash
sudo journalctl -u litchain -f
```

2. Check Nginx logs:
```bash
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/nginx/access.log
```

### 5. SSL Certificate Management
To regenerate the self-signed certificate:
```bash
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/nginx/ssl/litchain.key \
    -out /etc/nginx/ssl/litchain.crt \
    -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost"
sudo systemctl restart nginx
```

## Security Considerations
1. Update the default admin credentials in app.py
2. Configure AWS Security Groups to allow only necessary traffic:
   - Port 80 (HTTP)
   - Port 443 (HTTPS)
   - Port 22 (SSH)
3. Set up AWS WAF for additional security
4. Enable AWS CloudWatch for monitoring
5. For production, replace self-signed certificate with a proper SSL certificate

## Backup Strategy
1. Set up automated database backups
2. Configure EC2 instance backups
3. Store backups in S3
4. Backup SSL certificates:
```bash
sudo cp /etc/nginx/ssl/litchain.* /backup/ssl/
```

## Scaling
1. Set up an Application Load Balancer
2. Configure Auto Scaling Group
3. Use RDS read replicas if needed

## Troubleshooting
1. Check service status:
```bash
sudo systemctl status litchain
```

2. Check Nginx status:
```bash
sudo systemctl status nginx
```

3. View application logs:
```bash
sudo journalctl -u litchain -f
```

4. SSL Certificate Issues:
```bash
# Check certificate validity
openssl x509 -in /etc/nginx/ssl/litchain.crt -text -noout

# Check Nginx SSL configuration
sudo nginx -t
```

## Production Considerations
When moving to production:
1. Replace self-signed certificate with a proper SSL certificate (Let's Encrypt or commercial)
2. Update DNS records to point to your domain
3. Configure proper security headers in Nginx
4. Set up proper monitoring and alerting
5. Implement proper backup and disaster recovery procedures 