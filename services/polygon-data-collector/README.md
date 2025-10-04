# Polygon Data Collector Service

A microservice for collecting and processing ticker data from Polygon.io API.

## Features

- Real-time and historical data collection
- Technical analysis and sentiment analysis
- CSV/JSON export capabilities
- Rate limiting and error handling
- Configurable data processing

## Quick Start

1. **Set up environment variables:**
   ```bash
   cp ../../env.example .env
   # Edit .env with your Polygon API key
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the service:**
   ```bash
   python src/main.py --tickers AAPL GOOGL MSFT
   ```

## Usage Examples

```bash
# Collect data for specific tickers
python src/main.py --tickers AAPL GOOGL MSFT --days 30

# Search and collect data
python src/main.py --search "technology" --limit 50

# Collect top tickers by volume
python src/main.py --top 100 --days 7
```

## API Endpoints

- `GET /health` - Health check
- `POST /collect` - Collect data for tickers
- `GET /status` - Get market status
- `GET /report` - Generate analysis report

## Configuration

See `env.example` for all available configuration options.
