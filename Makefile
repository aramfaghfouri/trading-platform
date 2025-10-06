# Trading Platform Makefile
# Provides convenient commands for development and deployment

.PHONY: help install install-dev test lint format clean docker-up docker-down docker-logs setup-env

# Default target
help:
	@echo "Trading Platform - Available Commands:"
	@echo ""
	@echo "Development:"
	@echo "  install      Install production dependencies"
	@echo "  install-dev  Install development dependencies"
	@echo "  test         Run tests"
	@echo "  lint         Run linting checks"
	@echo "  format       Format code with black and isort"
	@echo "  clean        Clean up temporary files"
	@echo ""
	@echo "Docker:"
	@echo "  docker-up    Start Docker services"
	@echo "  docker-down  Stop Docker services"
	@echo "  docker-logs  View Docker logs"
	@echo ""
	@echo "Setup:"
	@echo "  setup-env    Set up development environment"
	@echo "  setup-db     Set up database"
	@echo "  setup-config Set up configuration files"

# Installation
install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements.txt
	pip install -e ".[dev]"

# Testing
test:
	pytest tests/ -v --cov=src --cov-report=html --cov-report=term-missing

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

# Code Quality
lint:
	flake8 src/ tests/
	mypy src/
	black --check src/ tests/
	isort --check-only src/ tests/

format:
	black src/ tests/
	isort src/ tests/

# Cleanup
clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf build/
	rm -rf dist/
	rm -rf .coverage
	rm -rf htmlcov/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/

# Docker Commands
docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

docker-build:
	docker-compose build

# Database Commands
setup-db:
	docker-compose up -d timescaledb
	@echo "Waiting for database to be ready..."
	sleep 10
	@echo "Database is ready!"

db-migrate:
	python scripts/migrate_database.py

db-seed:
	python scripts/seed_database.py

# Configuration
setup-config:
	@if [ ! -f .env ]; then \
		cp env.example .env; \
		echo "Created .env file from env.example"; \
		echo "Please edit .env with your actual configuration values"; \
	else \
		echo ".env file already exists"; \
	fi

# Development Environment Setup
setup-env: setup-config setup-db
	@echo "Development environment setup complete!"
	@echo "Next steps:"
	@echo "1. Edit .env file with your API keys and configuration"
	@echo "2. Run 'make install-dev' to install dependencies"
	@echo "3. Run 'make test' to verify everything is working"

# Pre-commit hooks
install-hooks:
	pre-commit install

# Documentation
docs:
	cd docs && make html

docs-serve:
	cd docs && python -m http.server 8000

# Monitoring
monitor:
	docker-compose up -d prometheus grafana

# Backup
backup:
	python scripts/backup_database.py

# Deployment
deploy-staging:
	@echo "Deploying to staging environment..."
	# Add staging deployment commands here

deploy-production:
	@echo "Deploying to production environment..."
	# Add production deployment commands here

# Security
security-check:
	bandit -r src/
	safety check

# Performance
profile:
	python -m cProfile -o profile.stats scripts/profile_performance.py

# Database Management
db-backup:
	docker exec trading_timescaledb pg_dump -U trading_user trading_platform > backup_$(shell date +%Y%m%d_%H%M%S).sql

db-restore:
	@echo "Usage: make db-restore BACKUP_FILE=backup_file.sql"
	@if [ -z "$(BACKUP_FILE)" ]; then \
		echo "Please specify BACKUP_FILE"; \
		exit 1; \
	fi
	docker exec -i trading_timescaledb psql -U trading_user trading_platform < $(BACKUP_FILE)

# Logs
logs:
	tail -f logs/trading_platform.log

logs-error:
	tail -f logs/errors.log

# System Status
status:
	@echo "=== Docker Services ==="
	docker-compose ps
	@echo ""
	@echo "=== Database Status ==="
	docker exec trading_timescaledb psql -U trading_user -d trading_platform -c "SELECT version();"
	@echo ""
	@echo "=== Disk Usage ==="
	df -h
	@echo ""
	@echo "=== Memory Usage ==="
	free -h
