#!/usr/bin/env python3
"""
Development environment setup script.

This script sets up the development environment for the trading platform.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
from typing import List, Optional


def run_command(command: str, cwd: Optional[Path] = None) -> bool:
    """
    Run a shell command and return success status.
    
    Args:
        command: Command to run
        cwd: Working directory
        
    Returns:
        True if command succeeded, False otherwise
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True
        )
        print(f"✅ {command}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {command}")
        print(f"   Error: {e.stderr}")
        return False


def check_python_version() -> bool:
    """Check if Python version is compatible."""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print(f"❌ Python {version.major}.{version.minor} is not supported")
        print("   Please use Python 3.8 or higher")
        return False
    
    print(f"✅ Python {version.major}.{version.minor}.{version.micro}")
    return True


def check_docker() -> bool:
    """Check if Docker is installed and running."""
    if not shutil.which("docker"):
        print("❌ Docker is not installed")
        print("   Please install Docker from https://docker.com")
        return False
    
    if not run_command("docker --version"):
        return False
    
    if not run_command("docker-compose --version"):
        return False
    
    return True


def setup_environment_file() -> bool:
    """Set up environment file from example."""
    env_file = Path(".env")
    env_example = Path("env.example")
    
    if env_file.exists():
        print("✅ .env file already exists")
        return True
    
    if not env_example.exists():
        print("❌ env.example file not found")
        return False
    
    try:
        shutil.copy(env_example, env_file)
        print("✅ Created .env file from env.example")
        print("   Please edit .env with your actual configuration values")
        return True
    except Exception as e:
        print(f"❌ Failed to create .env file: {e}")
        return False


def create_directories() -> bool:
    """Create necessary directories."""
    directories = [
        "logs",
        "data/raw",
        "data/processed", 
        "data/features",
        "data/backtests",
        "notebooks",
        "research",
        "models",
        "backups"
    ]
    
    for directory in directories:
        dir_path = Path(directory)
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
            print(f"✅ Created directory: {directory}")
        except Exception as e:
            print(f"❌ Failed to create directory {directory}: {e}")
            return False
    
    return True


def install_dependencies() -> bool:
    """Install Python dependencies."""
    commands = [
        "pip install --upgrade pip",
        "pip install -r requirements.txt",
        "pip install -e .[dev]"
    ]
    
    for command in commands:
        if not run_command(command):
            return False
    
    return True


def setup_pre_commit_hooks() -> bool:
    """Set up pre-commit hooks."""
    if not run_command("pre-commit install"):
        print("⚠️  Pre-commit hooks not installed (optional)")
        return True  # Not critical
    
    return True


def setup_docker_services() -> bool:
    """Set up Docker services."""
    if not run_command("docker-compose up -d timescaledb"):
        return False
    
    print("⏳ Waiting for database to be ready...")
    import time
    time.sleep(10)
    
    # Test database connection
    if not run_command("docker exec trading_timescaledb psql -U trading_user -d trading_platform -c 'SELECT version();'"):
        print("⚠️  Database connection test failed")
        return False
    
    return True


def run_tests() -> bool:
    """Run basic tests to verify setup."""
    if not run_command("python -m pytest tests/unit/ -v"):
        print("⚠️  Some tests failed (this may be expected for initial setup)")
        return True  # Not critical for setup
    
    return True


def main():
    """Main setup function."""
    print("🚀 Setting up Trading Platform Development Environment")
    print("=" * 60)
    
    # Check prerequisites
    print("\n📋 Checking Prerequisites...")
    if not check_python_version():
        sys.exit(1)
    
    if not check_docker():
        sys.exit(1)
    
    # Setup steps
    print("\n🔧 Setting up Environment...")
    if not setup_environment_file():
        sys.exit(1)
    
    if not create_directories():
        sys.exit(1)
    
    print("\n📦 Installing Dependencies...")
    if not install_dependencies():
        sys.exit(1)
    
    print("\n🪝 Setting up Pre-commit Hooks...")
    setup_pre_commit_hooks()
    
    print("\n🐳 Setting up Docker Services...")
    if not setup_docker_services():
        sys.exit(1)
    
    print("\n🧪 Running Tests...")
    run_tests()
    
    print("\n✅ Development Environment Setup Complete!")
    print("\n📝 Next Steps:")
    print("1. Edit .env file with your API keys and configuration")
    print("2. Run 'make test' to verify everything is working")
    print("3. Start developing!")
    print("\n🔗 Useful Commands:")
    print("  make help          - Show all available commands")
    print("  make test          - Run tests")
    print("  make lint          - Run linting")
    print("  make format        - Format code")
    print("  make docker-up     - Start Docker services")
    print("  make docker-down   - Stop Docker services")
    print("  make logs          - View logs")


if __name__ == "__main__":
    main()
