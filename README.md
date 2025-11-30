# SimpleNote 📝

A modern, feature-rich note-taking application with AI integration, built with React and Flask.

---

## ✨ Features

- 📝 **Rich Text Editor** - Format text, create lists, add tables
- 🎨 **Dark/Light Mode** - Beautiful UI with theme switching
- 🗄️ **PostgreSQL Database** - Reliable data persistence
- 📤 **File Import** - Upload .docx and .txt files
- 📥 **PDF Export** - Download notes as PDF
- 🖼️ **Media Support** - Embed images and videos
- 🔗 **Link Management** - Create hyperlinks easily
- 🎯 **Sub-lists** - Tab for nested lists
- 🧹 **Clear Formatting** - Remove all formatting
- 🔍 **AI Tools Ready** - Prepared for AI integration
- 💾 **Auto-save** - Never lose your work
- 🎨 **Color Palette** - Highlight important text
- 📊 **Tables** - Create structured data
- 🔄 **Real-time Updates** - Changes saved instantly

---

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- Make (optional, but recommended)
- 2GB RAM minimum

### Installation

```bash
# Clone the repository
git clone <your-repo>
cd simpleNote

# Build and start services
make build
make start

# Access the application
# Frontend: http://localhost:3002
# Backend:  http://localhost:5002
```

**That's it!** 🎉

---

## 📋 Using Make Commands

### Essential Commands

```bash
make start          # Start all services
make stop           # Stop all services
make restart        # Restart all services
make logs           # View logs
make status         # Check service status
make health         # Health check
```

### Database Commands

```bash
make psql           # Connect to database
make backup         # Backup database
make restore        # Restore from backup
make db-list        # List documents
make db-count       # Count documents
```

### Build & Deploy

```bash
make build          # Build all images
make deploy         # Full deployment
make prod           # Production deployment script
```

### Help

```bash
make help           # Show all commands
make quick-start    # Quick start guide
```

See [MAKEFILE_GUIDE.md](MAKEFILE_GUIDE.md) for complete documentation.

---

## 📁 Project Structure

```
simpleNote/
├── frontend/               # React frontend
│   ├── src/
│   │   ├── components/    # React components
│   │   │   ├── Editor.jsx
│   │   │   ├── Toolbar.jsx
│   │   │   ├── Sidebar.jsx
│   │   │   ├── AIPanel.jsx
│   │   │   └── Toast.jsx
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── Dockerfile
│   └── package.json
├── backend_flask/         # Flask backend
│   ├── app_postgres.py   # PostgreSQL version
│   ├── requirements.txt
│   └── ...
├── docker-compose.yml     # Services orchestration
├── Makefile              # Management commands
├── deploy-simplenote.sh  # Production deployment
└── wait-for-db.sh        # Database startup script
```

---

## 🗄️ Database

SimpleNote uses **PostgreSQL 15** for data persistence.

### Ports

- **5433** - External port (avoid conflict with 5432)
- **5432** - Internal container port

### Connection

```bash
# Via Makefile
make psql

# Direct connection
psql -h localhost -p 5433 -U simplenote_user -d simplenote
```

**Password:** `simplenote_secure_password_2024` (change in production!)

See [POSTGRES_SETUP.md](POSTGRES_SETUP.md) for complete database documentation.

---

## 🔧 Configuration

### Ports

| Service | Port |
|---------|------|
| Frontend | 3002 |
| Backend | 5002 |
| Database | 5433 |

### Environment Variables

See `.env.example` for configuration options.

**To customize:**
```bash
cp .env.example .env
# Edit .env with your values
```

### Memory Limits

| Container | Memory | CPU |
|-----------|--------|-----|
| PostgreSQL | 256MB | 0.3 |
| Backend | 256MB | 0.5 |
| Frontend | 128MB | 0.3 |
| **Total** | **640MB** | **1.1** |

---

## 🔐 Security

### Change Default Password!

**Important:** Change the default PostgreSQL password before production:

1. Generate secure password:
```bash
openssl rand -base64 32
```

2. Update `docker-compose.yml`:
   - `simplenote-db` environment
   - `simplenote-backend` DATABASE_URL

3. Restart services:
```bash
make restart
```

---

## 💾 Backup & Restore

### Backup

```bash
# Simple backup
make backup

# Compressed backup
make backup-compress
```

Backups are saved to `backups/backup_YYYYMMDD_HHMMSS.sql`

### Restore

```bash
make restore
# Enter backup filename when prompted
```

### Manual Backup

```bash
docker compose exec -T simplenote-db pg_dump -U simplenote_user simplenote > my_backup.sql
```

---

## 📊 Monitoring

### Service Status

```bash
make status         # Container status
make health         # Health checks
make stats          # Resource usage
make test           # Connectivity tests
```

### Logs

```bash
make logs           # All services
make logs-backend   # Backend only
make logs-frontend  # Frontend only
make logs-db        # Database only
```

### View Logs Script

```bash
./view-logs.sh      # Interactive log viewer
```

---

## 🚀 Deployment

### Development

```bash
make dev            # Start with live logs
```

### Production (EC2)

```bash
# First time
./deploy-simplenote.sh

# Updates
make deploy
```

See [PORT_ALLOCATION.md](PORT_ALLOCATION.md) for multi-service setup.

---

## 🔄 Updates

```bash
# Pull latest and restart
make update

# Full rebuild
make deploy
```

---

## 🛠️ Troubleshooting

### Services won't start

```bash
make status         # Check running services
make logs           # View error logs
make health         # Test connectivity
```

### Port conflicts

```bash
make ports          # Check port usage
lsof -i :3002       # Check specific port
```

### Database connection failed

```bash
make logs-db        # Check database logs
make psql           # Try to connect
```

### Out of memory

```bash
make stop           # Stop services
make prune          # Clean Docker
make start          # Restart
```

### Reset everything

```bash
make clean          # ⚠️ Deletes all data!
make build          # Rebuild images
make start          # Fresh start
```

---

## 📚 Documentation

- [Makefile Guide](MAKEFILE_GUIDE.md) - Complete Makefile documentation
- [PostgreSQL Setup](POSTGRES_SETUP.md) - Database configuration and management
- [Port Allocation](PORT_ALLOCATION.md) - Multi-service port management

---

## 🏗️ Architecture

### Frontend
- **React** 18 with Vite
- **Tailwind CSS** for styling
- **Document Commands** for editing
- **Responsive Design**

### Backend
- **Flask** 3.0 (Python)
- **psycopg2** for PostgreSQL
- **RESTful API**
- **Health checks**

### Database
- **PostgreSQL 15 Alpine**
- **Indexed queries**
- **Volume persistence**
- **Automatic initialization**

### Deployment
- **Docker Compose**
- **Nginx** for serving
- **Low-memory optimized**
- **Swap support**

---

## 🎯 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/documents` | GET | Get all documents |
| `/api/documents` | POST | Create document |
| `/api/documents/:id` | PUT | Update document |
| `/api/documents/:id` | DELETE | Delete document |

---

## 🧪 Testing

```bash
# Run connectivity tests
make test

# Health check
make health

# Manual test
curl http://localhost:5002/api/health
curl http://localhost:3002
```

---

## 🤝 Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature-name`
3. Commit changes: `git commit -m 'Add feature'`
4. Push to branch: `git push origin feature-name`
5. Submit pull request

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- React team for the amazing framework
- Flask community for the lightweight backend
- PostgreSQL for reliable database
- Tailwind CSS for beautiful styling

---

## 📞 Support

Having issues? Check these resources:

1. [Makefile Guide](MAKEFILE_GUIDE.md) - Command reference
2. [PostgreSQL Setup](POSTGRES_SETUP.md) - Database help
3. [Troubleshooting](#-troubleshooting) - Common issues
4. Run `make help` - Quick command reference

---

## 🎉 Quick Commands Cheat Sheet

```bash
# Start/Stop
make start          # Start services
make stop           # Stop services
make restart        # Restart services

# Logs
make logs           # View logs
make logs-backend   # Backend logs

# Database
make psql           # Database console
make backup         # Backup database

# Health
make status         # Service status
make health         # Health check

# Help
make help           # All commands
```

---

**Built with ❤️ for productivity**

🚀 Happy note-taking!

Inside .ssh/config/
# EC2 SimpleNote Server
Host simplenote-ec2
	HostName ec2-44-192-13-139.compute-1.amazonaws.com
	User ubuntu
	IdentityFile /Users/ramchandrab/Downloads/simpnote-ssh.pem
	StrictHostKeyChecking no
	UserKnownHostsFile /dev/null