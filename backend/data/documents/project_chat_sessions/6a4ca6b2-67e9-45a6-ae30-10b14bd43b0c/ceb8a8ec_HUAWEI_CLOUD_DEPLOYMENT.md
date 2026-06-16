# Huawei Cloud Deployment Guide

## Overview

This guide walks you through deploying the Enterprise Competitive Analysis Agent to Huawei Cloud (华为云) using Docker for easy setup and management.

---

## 📋 Architecture

```
Huawei Cloud ECS (Ubuntu 22.04)
├── Docker Container
│   ├── Backend (LangGraph + FastAPI)
│   │   ├── Port: 2024
│   │   └── LLM: Ollama (inside container)
│   └── Frontend (Nginx + React)
│       ├── Port: 80
│       └── Static files from /frontend/dist
└── Domain: your-domain.com
```

---

## � Network Access: Google, GitHub, and International Websites

### **Important: China Mainland vs International Regions**

#### **Option A: China Mainland Regions (上海/北京)**
- ❌ **Cannot access Google, GitHub, YouTube, etc.**
- ✅ Lower latency within China
- ✅ Better for Chinese users
- ✅ Cheaper pricing
- ⚠️ Requires VPN for accessing international services

#### **Option B: International Regions (Singapore/Hong Kong)**
- ✅ **Can access Google, GitHub, YouTube, etc.**
- ✅ Better for international teams
- ✅ No firewall restrictions
- ⚠️ Slightly higher latency to China mainland
- ⚠️ May have higher pricing

---

## 🎯 Prerequisites

1. **Huawei Cloud Account**: [https://www.huaweicloud.com](https://www.huaweicloud.com)
2. **Domain Name**: Optional but recommended (¥50-100/year)
3. **Local Development Environment**: Python 3.12+, Node.js 18+

---

## �🎯 Prerequisites

1. **Huawei Cloud Account**: [https://www.huaweicloud.com](https://www.huaweicloud.com)
2. **Domain Name**: Optional but recommended (¥50-100/year)
3. **Local Development Environment**: Python 3.12+, Node.js 18+

---

## 🚀 Step-by-Step Deployment

### Step 1: Create Huawei Cloud ECS Instance

#### 1.1 Login to Huawei Cloud Console
- Go to [Huawei Cloud Console](https://console.huaweicloud.com)
- Navigate to **ECS (Elastic Cloud Server)**

#### 1.2 Create New Instance
- **Region**: 华东1 (上海) or 华北2 (北京) - best performance
- **Availability Zone**: Any (default)
- **Instance Type**: 
  - **Recommended**: `c7.large.2` (2 vCPUs, 4GB RAM)
  - **Budget**: `s6.large.2` (2 vCPUs, 4GB RAM)
- **Image**: 
  - **OS**: Ubuntu 22.04 64bit (recommended)
  - **Alternative**: CentOS 7.9
- **Storage**: 
  - System Disk: 50GB SSD (recommended)
  - Data Disk: Optional (for reports storage)
- **Bandwidth**: 
  - 5Mbps (sufficient for most use cases)
  - Billing: Pay-per-day (按天计费)
- **Security Group**:
  - Allow TCP: 22 (SSH), 80 (HTTP), 443 (HTTPS), 2024 (Backend)
- **Key Pair**: Create new key pair (download .pem file)

#### 1.3 Instance Configuration Summary
```
Instance Type: c7.large.2 (2 vCPUs, 4GB RAM)
OS: Ubuntu 22.04 64bit
Storage: 50GB SSD
Bandwidth: 5Mbps
Region: 华东1 (上海)
Security Group: Allow ports 22, 80, 443, 2024
```

#### 1.4 Estimated Cost
- **c7.large.2**: ¥99-150/month (promotion) or ¥200-300/month (regular)
- **s6.large.2**: ¥70-120/month (budget option)
- **50GB SSD**: ¥10-20/month
- **5Mbps Bandwidth**: ¥20-30/month
- **Total**: ¥150-250/month (or ¥1800-3000/year)

**Tip**: Purchase for 3 years to get 45% discount!

---

### Step 2: Connect to Your ECS Instance

#### 2.1 SSH Connection (macOS/Linux)
```bash
# Navigate to your key pair directory
cd ~/Downloads

# Set correct permissions
chmod 600 your-key-pair.pem

# Connect to ECS
ssh -i "your-key-pair.pem" ubuntu@YOUR_ECS_PUBLIC_IP

# Example:
# ssh -i "my-huawei-key.pem" ubuntu@123.123.123.123
```

#### 2.2 SSH Connection (Windows)
- Use PuTTY or Windows Terminal
- Convert .pem to .ppk format using PuTTYgen
- Connect using the public IP

---

### Step 3: Install Docker and Docker Compose

```bash
# Update package list
sudo apt update

# Install Docker
sudo apt install -y docker.io

# Start Docker service
sudo systemctl start docker
sudo systemctl enable docker

# Install Docker Compose
sudo apt install -y docker-compose-plugin

# Verify installation
docker --version
docker-compose --version

# Add current user to docker group (optional, for without sudo)
sudo usermod -aG docker $USER
```

---

### Step 4: Clone Your Project

```bash
# Navigate to home directory
cd ~

# Clone your repository (replace with your actual repo URL)
git clone https://github.com/your-username/my-deep-agent.git
cd my-deep-agent

# Or if using SSH:
# git clone git@github.com:your-username/my-deep-agent.git
```

---

### Step 5: Prepare Backend Configuration

#### 5.1 Update `.env` File

Create a new `.env` file on the server:

```bash
# Create .env file
nano .env
```

Add the following configuration:

```bash
# ============================================================================
# LLM Configuration
# ============================================================================

# Manager LLM (Choose one option below)

# Option 1: Use Ollama (recommended for local LLM)
MANAGER_MODEL=ollama
MANAGER_OLLAMA_MODEL=qwen2.5:14b

# Option 2: Use DeepSeek API (cloud-based)
# MANAGER_MODEL=deepseek
# MANAGER_DEEPSEEK_MODEL=deepseek-chat
# DEEPSEEK_API_KEY=your_deepseek_api_key_here

# Option 3: Use Groq API (cloud-based, fast)
# MANAGER_MODEL=groq
# GROQ_API_KEY=your_groq_api_key_here

# Researcher LLM
RESEARCHER_MODEL=ollama
RESEARCHER_OLLAMA_MODEL=qwen2.5:32b

# Analyzer LLM
ANALYZER_MODEL=ollama
ANALYZER_OLLAMA_MODEL=qwen2.5:32b

# ============================================================================
# Frontend Configuration
# ============================================================================

# Backend API URL (use internal IP for Docker networking)
VITE_LANGGRAPH_URL=http://localhost:2024

# ============================================================================
# Other Settings
# ============================================================================

# Logging
LOG_LEVEL=INFO
```

**Save and exit**: Press `Ctrl+X`, then `Y`, then `Enter`

#### 5.2 Copy `.env` to Container

The `.env` file will be mounted to the Docker container automatically.

---

### Step 6: Create Docker Configuration

#### 6.1 Create `Dockerfile`

Create a new file `Dockerfile` in the project root:

```bash
nano Dockerfile
```

Add the following content:

```dockerfile
# =============================================================================
# Dockerfile for Enterprise Competitive Analysis Agent
# =============================================================================

# Stage 1: Build frontend
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# Copy frontend dependencies
COPY frontend/package*.json ./

RUN npm install

# Copy frontend source
COPY frontend/ ./

# Build frontend
RUN npm run build

# Stage 2: Backend runtime
FROM python:3.12-slim

# Install Node.js for Ollama
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Ollama
RUN curl -fsSL https://ollama.com/install.sh | sh

# Create working directory
WORKDIR /app

# Copy Python dependencies
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && \
    uv sync --frozen

# Copy project files
COPY . .

# Copy built frontend
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Create reports directory
RUN mkdir -p reports

# Expose ports
EXPOSE 2024 3001

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Run Ollama in background and start backend
CMD ["sh", "-c", "ollama serve & sleep 5 && uv run langgraph dev --port 2024 --host 0.0.0.0"]
```

**Save and exit**: Press `Ctrl+X`, then `Y`, then `Enter`

#### 6.2 Create `docker-compose.yml`

```bash
nano docker-compose.yml
```

Add the following content:

```yaml
# =============================================================================
# Docker Compose for Enterprise Competitive Analysis Agent
# =============================================================================

version: '3.8'

services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: deep-agent-backend
    ports:
      - "2024:2024"
    volumes:
      - ./reports:/app/reports
      - ./frontend/dist:/app/frontend/dist
      - ./agent_cli.py:/app/agent_cli.py
      - ./agent.py:/app/agent.py
      - ./chat_character_prompts.py:/app/chat_character_prompts.py
      - ./.env:/app/.env
    environment:
      - PYTHONUNBUFFERED=1
      - PYTHONDONTWRITEBYTECODE=1
    restart: unless-stopped
    privileged: true
    network_mode: "host"

  frontend:
    image: nginx:alpine
    container_name: deep-agent-frontend
    ports:
      - "80:80"
    volumes:
      - ./frontend/dist:/usr/share/nginx/html
      - ./nginx.conf:/etc/nginx/conf.d/default.conf
    depends_on:
      - backend
    restart: unless-stopped
```

**Save and exit**: Press `Ctrl+X`, then `Y`, then `Enter`

#### 6.3 Create `nginx.conf`

```bash
nano nginx.conf
```

Add the following content:

```nginx
# =============================================================================
# Nginx Configuration for Frontend
# =============================================================================

server {
    listen 80;
    server_name localhost;

    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api {
        proxy_pass http://localhost:2024;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws {
        proxy_pass http://localhost:2024;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "Upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }
}
```

**Save and exit**: Press `Ctrl+X`, then `Y`, then `Enter`

---

### Step 7: Build and Run Docker Containers

```bash
# Ensure you're in the project root directory
cd ~/my-deep-agent

# Build Docker images
docker-compose build

# Start containers
docker-compose up -d

# Check container status
docker-compose ps

# View logs
docker-compose logs -f
```

**Wait for Ollama to start** (about 30-60 seconds), then verify:

```bash
# Check if backend is running
curl http://localhost:2024

# Should return: {"status":"ok"} or similar
```

---

### Step 8: Test the Application

#### 8.1 Test Backend API

```bash
# Test backend health
curl http://localhost:2024

# Test chat endpoint
curl -X POST http://localhost:2024/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello"}],
    "company_name": "Test",
    "current_phase": "phase1"
  }'
```

#### 8.2 Test Frontend

Open your browser and navigate to:

```
http://YOUR_ECS_PUBLIC_IP
```

You should see the application interface.

---

### Step 9: Configure Domain (Optional but Recommended)

#### 9.1 Purchase Domain

Purchase a domain from:
- **阿里云**: https://wanwang.aliyun.com
- **腾讯云**: https://dnspod.cloud.tencent.com
- **华为云**: https://www.huaweicloud.com/product/domain.html

**Cost**: ¥50-100/year

#### 9.2 Configure DNS

1. **Login to Domain Provider Console**
2. **Add A Record**:
   - **Host**: @ (for your-domain.com)
   - **Value**: YOUR_ECS_PUBLIC_IP
   - **TTL**: 600 seconds

3. **Add A Record for www**:
   - **Host**: www
   - **Value**: YOUR_ECS_PUBLIC_IP
   - **TTL**: 600 seconds

#### 9.3 Update Nginx Configuration

Edit `nginx.conf`:

```nginx
server {
    listen 80;
    server_name your-domain.com www.your-domain.com;  # Replace with your domain

    # ... rest of configuration
}
```

Restart Nginx:

```bash
docker-compose restart frontend
```

---

### Step 10: Configure SSL/HTTPS (Optional but Recommended)

#### 10.1 Install Certbot

```bash
# On ECS instance
sudo apt install -y certbot python3-certbot-nginx
```

#### 10.2 Obtain SSL Certificate

```bash
# Stop nginx temporarily
docker-compose stop frontend

# Obtain certificate
certbot certonly --standalone -d your-domain.com -d www.your-domain.com

# Start nginx
docker-compose start frontend
```

#### 10.3 Update Nginx for HTTPS

Create `nginx-https.conf`:

```nginx
server {
    listen 80;
    server_name your-domain.com www.your-domain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com www.your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers on;

    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api {
        proxy_pass http://localhost:2024;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }
}
```

---

## 📊 Maintenance

### 11.1 View Logs

```bash
# All logs
docker-compose logs -f

# Backend logs only
docker-compose logs -f backend

# Frontend logs only
docker-compose logs -f frontend
```

### 11.2 Restart Services

```bash
# Restart all services
docker-compose restart

# Restart specific service
docker-compose restart backend
docker-compose restart frontend
```

### 11.3 Stop Services

```bash
# Stop all services
docker-compose down

# Stop and remove volumes
docker-compose down -v
```

### 11.4 Update Application

```bash
# Pull latest changes
cd ~/my-deep-agent
git pull

# Rebuild and restart
docker-compose down
docker-compose build
docker-compose up -d
```

### 11.5 Backup Data

```bash
# Backup reports directory
tar -czf reports-backup-$(date +%Y%m%d).tar.gz reports/

# Backup to local machine
scp ubuntu@YOUR_ECS_PUBLIC_IP:~/my-deep-agent/reports-backup-*.tar.gz ~/backups/
```

---

## 🎯 LLM Options

### Option 1: Ollama (Local, Free)

**Pros**:
- ✅ Free
- ✅ Runs locally on ECS
- ✅ qwen2.5:14b with thinking capability

**Cons**:
- ⚠️ Requires ~8GB RAM
- ⚠️ Slower than API

**Configuration**: Already set up in `.env`

### Option 2: DeepSeek API (Cloud, Paid)

**Pros**:
- ✅ Fast
- ✅ No local compute required
- ✅ Reliable

**Cons**:
- ⚠️ Cost per token

**Configuration**:
```bash
MANAGER_MODEL=deepseek
MANAGER_DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_API_KEY=your_api_key_here
```

### Option 3: Groq API (Cloud, Paid)

**Pros**:
- ✅ Very fast
- ✅ Free tier available

**Cons**:
- ⚠️ Limited free tier

**Configuration**:
```bash
MANAGER_MODEL=groq
GROQ_API_KEY=your_api_key_here
```

---

## 💰 Cost Estimation

### Huawei Cloud ECS Pricing (2025)

#### c7.large.2 (2 vCPUs, 4GB RAM)
- **Promotional**: ¥99-150/month
- **Regular**: ¥200-300/month
- **3-year discount**: 45% off

#### s6.large.2 (2 vCPUs, 4GB RAM) - Budget Option
- **Promotional**: ¥70-120/month
- **Regular**: ¥150-200/month

#### Additional Costs
- **50GB SSD**: ¥10-20/month
- **5Mbps Bandwidth**: ¥20-30/month
- **Domain**: ¥50-100/year
- **SSL Certificate**: Free (Let's Encrypt)

#### Total Monthly Cost
- **Minimum (s6 + 50GB + 5Mbps)**: ¥100-150/month
- **Recommended (c7 + 50GB + 5Mbps)**: ¥150-250/month
- **Annual (with 3-year discount)**: ¥1000-2000/year

---

## 🚨 Troubleshooting

### Issue 1: Ollama Not Starting

```bash
# Check Ollama status
docker exec deep-agent-backend ollama list

# Pull model manually
docker exec deep-agent-backend ollama pull qwen2.5:14b

# Check Ollama logs
docker exec deep-agent-backend journalctl -u ollama
```

### Issue 2: Port Already in Use

```bash
# Check what's using port 2024
docker exec deep-agent-backend netstat -tlnp | grep :2024

# Kill process
docker exec deep-agent-backend pkill -f langgraph
```

### Issue 3: Frontend Not Loading

```bash
# Check Nginx logs
docker logs deep-agent-frontend

# Test Nginx configuration
docker exec deep-agent-frontend nginx -t

# Restart frontend
docker-compose restart frontend
```

### Issue 4: Connection Refused

```bash
# Check if backend is running
docker ps

# Check backend logs
docker logs deep-agent-backend

# Verify security group rules
# Ensure ports 22, 80, 443, 2024 are open
```

---

## 📚 Additional Resources

### Huawei Cloud Documentation
- [ECS Documentation](https://support.huaweicloud.com/product ecs.html)
- [Docker Documentation](https://support.huaweicloud.com/container docker.html)
- [Domain Service](https://support.huaweicloud.com/domain.html)

### Docker Documentation
- [Docker Official Docs](https://docs.docker.com)
- [Docker Compose](https://docs.docker.com/compose)

### Ollama Documentation
- [Ollama Docs](https://ollama.com/docs)

---

## ✅ Success Checklist

- [ ] ECS instance created and running
- [ ] SSH connection successful
- [ ] Docker installed and running
- [ ] Project cloned to ECS
- [ ] `.env` file configured
- [ ] Docker containers built and running
- [ ] Backend API accessible on port 2024
- [ ] Frontend accessible on port 80
- [ ] Domain configured (optional)
- [ ] SSL certificate installed (optional)
- [ ] Application tested with sample data

---

## 🎉 Next Steps

1. **Test the application** with your team
2. **Monitor performance** and adjust ECS规格 if needed
3. **Set up monitoring** (CloudEye on Huawei Cloud)
4. **Configure backups** for reports data
5. **Set up CI/CD** for automatic deployments

---

## 📞 Support

If you encounter issues:
1. Check logs: `docker-compose logs -f`
2. Review Huawei Cloud documentation
3. Contact Huawei Cloud support

---

**Happy Deploying! 🚀**
