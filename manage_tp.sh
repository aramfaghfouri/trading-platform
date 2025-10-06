#!/bin/bash

# Trading Platform Management Script
# Usage: ./manage_tp.sh [command] [options]

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if Docker is running
check_docker() {
    if ! docker info > /dev/null 2>&1; then
        print_error "Docker is not running. Please start Docker and try again."
        exit 1
    fi
}

# Function to check if required files exist
check_requirements() {
    local missing_files=()
    
    if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
        missing_files+=(".env")
    fi
    
    if [[ ! -f "$PROJECT_ROOT/project-setup.toml" ]]; then
        missing_files+=("project-setup.toml")
    fi
    
    if [[ ${#missing_files[@]} -gt 0 ]]; then
        print_error "Missing required files: ${missing_files[*]}"
        print_status "Please ensure .env and project-setup.toml exist in the project root."
        exit 1
    fi
}

# Function to delete all databases and containers
delete_databases() {
    print_status "Deleting all databases and containers..."
    
    # Stop and remove all containers with volumes
    print_status "Stopping and removing Docker containers..."
    docker-compose down -v --remove-orphans 2>/dev/null || true
    
    # Remove any remaining containers
    print_status "Cleaning up remaining containers..."
    docker container prune -f 2>/dev/null || true
    
    # Remove volumes
    print_status "Removing Docker volumes..."
    docker volume prune -f 2>/dev/null || true
    
    # Remove specific volumes if they exist
    docker volume rm trading-platform_timescaledb_data 2>/dev/null || true
    
    print_success "All databases and containers deleted successfully!"
}

# Function to start TimescaleDB
start_database() {
    print_status "Starting TimescaleDB..."
    
    # Start only the database service
    docker-compose up -d timescaledb
    
    # Wait for database to be ready
    print_status "Waiting for TimescaleDB to be ready..."
    local max_attempts=30
    local attempt=1
    
    while [[ $attempt -le $max_attempts ]]; do
        if docker exec trading_timescaledb pg_isready -U trading_user -d trading_platform > /dev/null 2>&1; then
            print_success "TimescaleDB is ready!"
            return 0
        fi
        
        print_status "Attempt $attempt/$max_attempts - waiting for database..."
        sleep 2
        ((attempt++))
    done
    
    print_error "TimescaleDB failed to start within expected time"
    exit 1
}

# Function to validate configuration
validate_config() {
    print_status "Validating configuration..."
    
    cd "$PROJECT_ROOT"
    eval "$(conda shell.bash hook)"
    conda activate env-trading
    python scripts/validate_config.py
    
    if [[ $? -eq 0 ]]; then
        print_success "Configuration validation passed!"
    else
        print_error "Configuration validation failed!"
        exit 1
    fi
}

# Function to collect data
collect_data() {
    print_status "Starting data collection..."
    
    cd "$PROJECT_ROOT"
    
    # Read configuration from project-setup.toml
    local time_interval=$(grep 'time_interval' project-setup.toml | cut -d'"' -f2)
    local start_date=$(grep 'start_date' project-setup.toml | cut -d'"' -f2)
    local end_date=$(grep 'end_date' project-setup.toml | cut -d'"' -f2)
    local tickers=$(grep -A 20 'tickers = \[' project-setup.toml | grep -E '^\s*"[A-Z]+"' | sed 's/.*"\([^"]*\)".*/\1/' | tr '\n' ' ')
    
    print_status "Configuration:"
    print_status "  Time Interval: $time_interval"
    print_status "  Start Date: $start_date"
    print_status "  End Date: $end_date"
    print_status "  Tickers: $tickers"
    
    # Activate conda environment and run data collection
    eval "$(conda shell.bash hook)"
    conda activate env-trading
    python src/data_collectors/polygon/main.py collect
    
    if [[ $? -eq 0 ]]; then
        print_success "Data collection completed successfully!"
    else
        print_error "Data collection failed!"
        exit 1
    fi
}

# Function to show database status
show_status() {
    print_status "Checking system status..."
    
    # Check if TimescaleDB is running
    if docker ps | grep -q "timescaledb"; then
        print_success "TimescaleDB is running"
        
        # Show database info using new ticker-specific tables
        print_status "Database information:"
        docker exec trading_timescaledb psql -U trading_user -d trading_platform -c "
            SELECT 
                symbol, 
                table_name,
                is_active,
                last_updated
            FROM ticker_registry 
            ORDER BY last_updated DESC 
            LIMIT 10;
        " 2>/dev/null || print_warning "No ticker registry found"
        
        # Show data counts for each ticker
        print_status "Data counts by ticker:"
        docker exec trading_timescaledb psql -U trading_user -d trading_platform -c "
            SELECT 
                symbol,
                COUNT(*) as records,
                MIN(timestamp) as earliest,
                MAX(timestamp) as latest
            FROM (
                SELECT symbol, timestamp FROM ohlcv_aapl_1m WHERE 1=0
                UNION ALL SELECT 'AAPL', timestamp FROM ohlcv_aapl_1m
                UNION ALL SELECT 'GOOGL', timestamp FROM ohlcv_googl_1m
                UNION ALL SELECT 'MSFT', timestamp FROM ohlcv_msft_1m
                UNION ALL SELECT 'TSLA', timestamp FROM ohlcv_tsla_1m
                UNION ALL SELECT 'AMZN', timestamp FROM ohlcv_amzn_1m
            ) data
            GROUP BY symbol 
            ORDER BY records DESC 
            LIMIT 10;
        " 2>/dev/null || print_warning "No data found in ticker tables"
    else
        print_warning "TimescaleDB is not running"
    fi
}

# Function to collect sample data for testing
collect_sample_data() {
    print_status "Collecting sample data for testing..."
    
    cd "$PROJECT_ROOT"
    
    # Activate conda environment and run sample data collection
    eval "$(conda shell.bash hook)"
    conda activate env-trading
    python src/data_collectors/polygon/main.py sample --symbols AAPL MSFT GOOGL TSLA AMZN --days 30
    
    if [[ $? -eq 0 ]]; then
        print_success "Sample data collection completed successfully!"
    else
        print_error "Sample data collection failed!"
        exit 1
    fi
}

# Function to debug the collector
debug_collector() {
    print_status "Debugging collector functionality..."
    
    cd "$PROJECT_ROOT"
    
    # Activate conda environment and run debug
    eval "$(conda shell.bash hook)"
    conda activate env-trading
    python src/data_collectors/polygon/main.py debug
    
    if [[ $? -eq 0 ]]; then
        print_success "Debug completed successfully!"
    else
        print_error "Debug failed!"
        exit 1
    fi
}

# Function to check database status in detail
check_database() {
    print_status "Checking database status in detail..."
    
    cd "$PROJECT_ROOT"
    
    # Activate conda environment and run status check
    eval "$(conda shell.bash hook)"
    conda activate env-trading
    python src/data_collectors/polygon/main.py status
    
    if [[ $? -eq 0 ]]; then
        print_success "Database status check completed!"
    else
        print_error "Database status check failed!"
        exit 1
    fi
}

# Function to migrate data from old structure
migrate_data() {
    print_status "Migrating data from old table structure..."
    
    cd "$PROJECT_ROOT"
    
    # Activate conda environment and run migration
    eval "$(conda shell.bash hook)"
    conda activate env-trading
    python src/data_collectors/polygon/scripts/migrate_to_ticker_tables.py --backup
    
    if [[ $? -eq 0 ]]; then
        print_success "Data migration completed successfully!"
    else
        print_error "Data migration failed!"
        exit 1
    fi
}

# Function to show help
show_help() {
    echo "Trading Platform Management Script"
    echo ""
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  --delete-databases    Delete all databases and containers"
    echo "  --start-database      Start TimescaleDB"
    echo "  --collect-data        Collect data for all configured tickers"
    echo "  --collect-sample      Collect sample data for testing (AAPL, MSFT, GOOGL, TSLA, AMZN)"
    echo "  --validate-config     Validate configuration files"
    echo "  --status              Show system status"
    echo "  --check-database      Check database status in detail"
    echo "  --debug-collector     Debug collector functionality"
    echo "  --migrate-data        Migrate data from old table structure"
    echo "  --help                Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 --delete-databases"
    echo "  $0 --start-database"
    echo "  $0 --collect-data"
    echo "  $0 --collect-sample"
    echo "  $0 --validate-config"
    echo "  $0 --status"
    echo "  $0 --check-database"
    echo "  $0 --debug-collector"
    echo "  $0 --migrate-data"
    echo ""
    echo "Full workflow:"
    echo "  $0 --delete-databases && $0 --start-database && $0 --collect-data"
    echo ""
    echo "Testing workflow:"
    echo "  $0 --start-database && $0 --collect-sample && $0 --check-database"
}

# Main script logic
main() {
    # Check if Docker is running
    check_docker
    
    # Check if we're in the right directory
    if [[ ! -f "$PROJECT_ROOT/docker-compose.yml" ]]; then
        print_error "docker-compose.yml not found. Please run this script from the project root."
        exit 1
    fi
    
    case "${1:-}" in
        --delete-databases)
            delete_databases
            ;;
        --start-database)
            start_database
            ;;
        --collect-data)
            check_requirements
            collect_data
            ;;
        --collect-sample)
            check_requirements
            collect_sample_data
            ;;
        --validate-config)
            check_requirements
            validate_config
            ;;
        --status)
            show_status
            ;;
        --check-database)
            check_requirements
            check_database
            ;;
        --debug-collector)
            check_requirements
            debug_collector
            ;;
        --migrate-data)
            check_requirements
            migrate_data
            ;;
        --help|-h)
            show_help
            ;;
        "")
            print_error "No command specified. Use --help for usage information."
            exit 1
            ;;
        *)
            print_error "Unknown command: $1"
            print_status "Use --help for usage information."
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"
