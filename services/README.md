# Trading Platform Services

This directory contains all microservices for the trading platform.

## Services Overview

### 1. Polygon Data Collector (`polygon-data-collector/`)
- **Purpose**: Collects ticker data from Polygon.io API
- **Port**: 8001
- **Features**: Real-time data collection, technical analysis, sentiment analysis
- **API Docs**: http://localhost:8001/docs

### 2. Database (`postgres/`)
- **Purpose**: Stores collected ticker data and platform data
- **Port**: 5432
- **Database**: trading_platform

### 3. Cache (`redis/`)
- **Purpose**: Caching for improved performance
- **Port**: 6379

### 4. API Gateway (`api-gateway/`)
- **Purpose**: Routes requests to appropriate services
- **Port**: 80

## Quick Start

1. **Set up environment variables:**
   ```bash
   cp ../env.example .env
   # Edit .env with your API keys and passwords
   ```

2. **Start all services:**
   ```bash
   docker-compose up -d
   ```

3. **Check service health:**
   ```bash
   curl http://localhost:8001/health
   ```

4. **View API documentation:**
   - Polygon Data Collector: http://localhost:8001/docs

## Individual Service Management

### Start specific service:
```bash
docker-compose up polygon-data-collector
```

### View logs:
```bash
docker-compose logs polygon-data-collector
```

### Scale service:
```bash
docker-compose up --scale polygon-data-collector=3
```

## Development

### Add new service:
1. Create new directory under `services/`
2. Add service to `docker-compose.yml`
3. Update this README

### Service communication:
- Services communicate via HTTP APIs
- Use service names as hostnames (e.g., `http://polygon-data-collector:8000`)
- All services are on the `trading-platform` network
