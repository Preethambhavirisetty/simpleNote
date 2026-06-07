.PHONY: help start stop restart logs logs-backend logs-frontend logs-db status build deploy clean backup restore psql health test

# Colors for output
GREEN  := \033[0;32m
YELLOW := \033[1;33m
BLUE   := \033[0;34m
RED    := \033[0;31m
NC     := \033[0m # No Color

# Default target
.DEFAULT_GOAL := help

help: ## Show this help message
	@echo "$(BLUE)╔════════════════════════════════════════╗$(NC)"
	@echo "$(BLUE)║   SimpleNote Makefile Commands        ║$(NC)"
	@echo "$(BLUE)╚════════════════════════════════════════╝$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""

start: ## Start all services
	@echo "$(GREEN)Starting SimpleNote...$(NC)"
	@docker compose up -d
	@echo "$(GREEN)✓ Services started$(NC)"
	@echo "Access at: http://localhost:3002"

stop: ## Stop all services
	@echo "$(YELLOW)Stopping SimpleNote...$(NC)"
	@docker compose down
	@echo "$(GREEN)✓ Services stopped$(NC)"

restart: ## Restart all services
	@echo "$(YELLOW)Restarting SimpleNote...$(NC)"
	@docker compose restart
	@echo "$(GREEN)✓ Services restarted$(NC)"

status: ## Show status of all services
	@echo "$(BLUE)Service Status:$(NC)"
	@docker compose ps

logs: ## View logs from all services (press Ctrl+C to exit)
	@docker compose logs -f

logs-backend: ## View backend logs only
	@docker compose logs -f simplenote-backend

logs-frontend: ## View frontend logs only
	@docker compose logs -f simplenote-frontend

logs-db: ## View database logs only
	@docker compose logs -f simplenote-db

logs-tail: ## View last 100 lines of all logs
	@docker compose logs --tail=100

build: ## Build all images
	@echo "$(YELLOW)Building images...$(NC)"
	@docker compose build --no-cache
	@echo "$(GREEN)✓ Build complete$(NC)"

build-backend: ## Build backend only
	@echo "$(YELLOW)Building backend...$(NC)"
	@docker compose build --no-cache simplenote-backend
	@echo "$(GREEN)✓ Backend built$(NC)"

build-frontend: ## Build frontend only
	@echo "$(YELLOW)Building frontend...$(NC)"
	@docker compose build --no-cache simplenote-frontend
	@echo "$(GREEN)✓ Frontend built$(NC)"

deploy: ## Full deployment (stop, build, start)
	@echo "$(BLUE)Running full deployment...$(NC)"
	@make stop
	@make build
	@make start
	@echo "$(GREEN)✓ Deployment complete!$(NC)"

clean: ## Stop services and remove volumes (WARNING: deletes data!)
	@echo "$(RED)⚠️  This will delete all data!$(NC)"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		docker compose down -v; \
		echo "$(GREEN)✓ Cleaned up$(NC)"; \
	else \
		echo "$(YELLOW)Cancelled$(NC)"; \
	fi

clean-images: ## Remove SimpleNote Docker images
	@echo "$(YELLOW)Removing SimpleNote images...$(NC)"
	@docker images | grep simplenote | awk '{print $$3}' | xargs -r docker rmi -f 2>/dev/null || true
	@echo "$(GREEN)✓ Images removed$(NC)"

psql: ## Connect to PostgreSQL database
	@docker compose exec simplenote-db psql -U simplenote_user -d simplenote

health: ## Check health of all services
	@echo "$(BLUE)Health Check:$(NC)"
	@echo -n "Backend:  "
	@curl -sf http://localhost:5002/api/health > /dev/null 2>&1 && echo "$(GREEN)✓ Healthy$(NC)" || echo "$(RED)✗ Unhealthy$(NC)"
	@echo -n "Frontend: "
	@curl -sf http://localhost:3002 > /dev/null 2>&1 && echo "$(GREEN)✓ Healthy$(NC)" || echo "$(RED)✗ Unhealthy$(NC)"
	@echo -n "Database: "
	@docker compose exec -T simplenote-db pg_isready -U simplenote_user > /dev/null 2>&1 && echo "$(GREEN)✓ Healthy$(NC)" || echo "$(RED)✗ Unhealthy$(NC)"

backup: ## Backup PostgreSQL database
	@echo "$(YELLOW)Creating backup...$(NC)"
	@mkdir -p backups
	@docker compose exec -T simplenote-db pg_dump -U simplenote_user simplenote > backups/backup_$$(date +%Y%m%d_%H%M%S).sql
	@echo "$(GREEN)✓ Backup created in backups/$(NC)"
	@ls -lh backups/ | tail -1

backup-compress: ## Backup and compress database
	@echo "$(YELLOW)Creating compressed backup...$(NC)"
	@mkdir -p backups
	@docker compose exec -T simplenote-db pg_dump -U simplenote_user simplenote | gzip > backups/backup_$$(date +%Y%m%d_%H%M%S).sql.gz
	@echo "$(GREEN)✓ Compressed backup created in backups/$(NC)"
	@ls -lh backups/ | tail -1

restore: ## Restore database from latest backup
	@echo "$(RED)⚠️  This will overwrite current data!$(NC)"
	@read -p "Enter backup filename (in backups/ folder): " backup; \
	if [ -f "backups/$$backup" ]; then \
		echo "$(YELLOW)Restoring from backups/$$backup...$(NC)"; \
		if [[ $$backup == *.gz ]]; then \
			gunzip -c backups/$$backup | docker compose exec -T simplenote-db psql -U simplenote_user simplenote; \
		else \
			cat backups/$$backup | docker compose exec -T simplenote-db psql -U simplenote_user simplenote; \
		fi; \
		echo "$(GREEN)✓ Restore complete$(NC)"; \
	else \
		echo "$(RED)✗ Backup file not found$(NC)"; \
	fi

shell-backend: ## Open shell in backend container
	@docker compose exec simplenote-backend /bin/sh

shell-frontend: ## Open shell in frontend container
	@docker compose exec simplenote-frontend /bin/sh

shell-db: ## Open shell in database container
	@docker compose exec simplenote-db /bin/sh

stats: ## Show resource usage statistics
	@docker stats --no-stream simplenote-backend simplenote-frontend simplenote-db

db-query: ## Run a SQL query (usage: make db-query QUERY="SELECT * FROM documents;")
	@docker compose exec -T simplenote-db psql -U simplenote_user -d simplenote -c "$(QUERY)"

db-count: ## Count documents in database
	@echo "$(BLUE)Document count:$(NC)"
	@docker compose exec -T simplenote-db psql -U simplenote_user -d simplenote -c "SELECT COUNT(*) as total_documents FROM documents;"

db-list: ## List all documents
	@echo "$(BLUE)Documents:$(NC)"
	@docker compose exec -T simplenote-db psql -U simplenote_user -d simplenote -c "SELECT id, title, created_at, updated_at FROM documents ORDER BY updated_at DESC LIMIT 10;"

db-size: ## Show database size
	@echo "$(BLUE)Database size:$(NC)"
	@docker compose exec -T simplenote-db psql -U simplenote_user -d simplenote -c "SELECT pg_size_pretty(pg_database_size('simplenote'));"

db-users: ## List all users
	@echo "$(BLUE)Registered users:$(NC)"
	@docker compose exec -T simplenote-db psql -U simplenote_user -d simplenote -c "SELECT id, name, email, created_at FROM users ORDER BY created_at DESC;"

db-stats: ## Show user and document statistics
	@echo "$(BLUE)User and Document Statistics:$(NC)"
	@docker compose exec -T simplenote-db psql -U simplenote_user -d simplenote -c "SELECT u.name, u.email, COUNT(d.id) as document_count FROM users u LEFT JOIN documents d ON u.id = d.user_id GROUP BY u.id, u.name, u.email ORDER BY document_count DESC;"

ports: ## Show port usage
	@echo "$(BLUE)Port Allocation:$(NC)"
	@echo "  Frontend:  3002"
	@echo "  Backend:   5002"
	@echo "  Database:  5433"
	@echo ""
	@echo "$(BLUE)Listening ports:$(NC)"
	@lsof -iTCP:3002,5002,5433 -sTCP:LISTEN 2>/dev/null || echo "  No ports in use"

update: ## Pull latest images and restart
	@echo "$(YELLOW)Updating SimpleNote...$(NC)"
	@docker compose pull
	@make restart
	@echo "$(GREEN)✓ Update complete$(NC)"

prune: ## Clean up Docker system (remove unused data)
	@echo "$(YELLOW)Pruning Docker system...$(NC)"
	@docker system prune -f
	@echo "$(GREEN)✓ Cleanup complete$(NC)"

prune-all: ## Deep clean - remove ALL unused Docker data (WARNING: aggressive)
	@echo "$(RED)⚠️  This will remove ALL unused containers, images, networks, and volumes!$(NC)"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		echo "$(YELLOW)Stopping SimpleNote containers...$(NC)"; \
		docker compose down; \
		echo "$(YELLOW)Removing all stopped containers...$(NC)"; \
		docker container prune -f; \
		echo "$(YELLOW)Removing all unused images...$(NC)"; \
		docker image prune -a -f; \
		echo "$(YELLOW)Removing all unused volumes...$(NC)"; \
		docker volume prune -f; \
		echo "$(YELLOW)Removing all unused networks...$(NC)"; \
		docker network prune -f; \
		echo "$(YELLOW)Final system cleanup...$(NC)"; \
		docker system prune -a -f --volumes; \
		echo "$(GREEN)✓ Deep cleanup complete$(NC)"; \
		echo "$(BLUE)Disk space reclaimed:$(NC)"; \
		docker system df; \
	else \
		echo "$(YELLOW)Cancelled$(NC)"; \
	fi

cleanup-simplenote: ## Remove only SimpleNote containers and images (keeps data)
	@echo "$(YELLOW)Cleaning up SimpleNote containers and images...$(NC)"
	@docker compose down
	@docker images | grep simplenote | awk '{print $$3}' | xargs -r docker rmi -f 2>/dev/null || true
	@echo "$(GREEN)✓ SimpleNote images removed (volumes preserved)$(NC)"

cleanup-dangling: ## Remove dangling images and containers
	@echo "$(YELLOW)Removing dangling images...$(NC)"
	@docker images -f "dangling=true" -q | xargs -r docker rmi 2>/dev/null || echo "No dangling images"
	@echo "$(YELLOW)Removing stopped containers...$(NC)"
	@docker container prune -f
	@echo "$(GREEN)✓ Dangling cleanup complete$(NC)"

docker-stats: ## Show Docker disk usage
	@echo "$(BLUE)Docker Disk Usage:$(NC)"
	@docker system df
	@echo ""
	@echo "$(BLUE)Detailed breakdown:$(NC)"
	@docker system df -v

free-space: ## Show available disk space before and after cleanup
	@echo "$(BLUE)Current disk usage:$(NC)"
	@df -h / | tail -1
	@echo ""
	@echo "$(YELLOW)Running cleanup...$(NC)"
	@docker system prune -f > /dev/null 2>&1
	@echo "$(BLUE)After cleanup:$(NC)"
	@df -h / | tail -1

test: ## Run basic connectivity tests
	@echo "$(BLUE)Running tests...$(NC)"
	@echo -n "Testing frontend (port 3002): "
	@curl -sf http://localhost:3002 > /dev/null && echo "$(GREEN)✓ Pass$(NC)" || echo "$(RED)✗ Fail$(NC)"
	@echo -n "Testing backend (port 5002):  "
	@curl -sf http://localhost:5002/api/health > /dev/null && echo "$(GREEN)✓ Pass$(NC)" || echo "$(RED)✗ Fail$(NC)"
	@echo -n "Testing database (port 5433): "
	@docker compose exec -T simplenote-db pg_isready -U simplenote_user > /dev/null && echo "$(GREEN)✓ Pass$(NC)" || echo "$(RED)✗ Fail$(NC)"

dev: ## Start services with live logs (Docker)
	@docker compose up

dev-local: ## Start development servers locally (no Docker)
	@./start-dev.sh

dev-stop: ## Stop local development servers
	@./stop-dev.sh

prod: ## Deploy in production mode
	@./deploy-simplenote.sh

info: ## Show system information
	@echo "$(BLUE)╔════════════════════════════════════════╗$(NC)"
	@echo "$(BLUE)║   SimpleNote System Information       ║$(NC)"
	@echo "$(BLUE)╚════════════════════════════════════════╝$(NC)"
	@echo ""
	@echo "$(YELLOW)Docker:$(NC)"
	@docker --version
	@docker compose version
	@echo ""
	@echo "$(YELLOW)Containers:$(NC)"
	@docker compose ps
	@echo ""
	@echo "$(YELLOW)Volumes:$(NC)"
	@docker volume ls | grep simplenote || echo "  No volumes found"
	@echo ""
	@echo "$(YELLOW)Images:$(NC)"
	@docker images | grep simplenote || echo "  No images found"

quick-start: ## Quick start guide
	@echo "$(BLUE)╔════════════════════════════════════════╗$(NC)"
	@echo "$(BLUE)║   SimpleNote Quick Start Guide        ║$(NC)"
	@echo "$(BLUE)╚════════════════════════════════════════╝$(NC)"
	@echo ""
	@echo "$(GREEN)First time setup:$(NC)"
	@echo "  1. make build    # Build all images"
	@echo "  2. make start    # Start services"
	@echo "  3. make health   # Verify everything is running"
	@echo ""
	@echo "$(GREEN)Daily usage:$(NC)"
	@echo "  make start       # Start services"
	@echo "  make stop        # Stop services"
	@echo "  make restart     # Restart services"
	@echo "  make logs        # View logs"
	@echo ""
	@echo "$(GREEN)Maintenance:$(NC)"
	@echo "  make backup      # Backup database"
	@echo "  make status      # Check service status"
	@echo "  make health      # Health check"
	@echo ""
	@echo "$(GREEN)Access:$(NC)"
	@echo "  http://localhost:3002  # Frontend"
	@echo "  http://localhost:5002  # Backend API"
	@echo "  make psql              # Database console"
	@echo ""

