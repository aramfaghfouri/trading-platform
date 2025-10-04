#!/usr/bin/env python3
"""
Install required packages for the trading platform
Uses conda/conda-forge when possible, falls back to pip
"""

import subprocess
import sys
import os

def run_command(command, description):
    """Run a command and handle errors"""
    print(f"Running: {description}")
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(f"✅ {description} - Success")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} - Failed: {e.stderr}")
        return False

def install_packages():
    """Install packages using conda and pip"""
    
    # Packages to install via conda-forge
    conda_packages = [
        "requests",
        "pandas", 
        "numpy",
        "scipy",
        "matplotlib",
        "plotly",
        "pytz",
        "tqdm",
        "lz4",
        "polars",
        "duckdb",
        "python-dotenv",
        "toml"
    ]
    
    # Packages to install via pip (not available in conda or better via pip)
    pip_packages = [
        "polygon-api-client",
        "fastapi",
        "uvicorn", 
        "pydantic"
    ]
    
    print("🚀 Installing packages for trading platform...")
    print("=" * 50)
    
    # Install conda packages
    print("\n📦 Installing packages via conda-forge...")
    for package in conda_packages:
        success = run_command(
            f"conda install -c conda-forge {package} -y",
            f"Installing {package} via conda-forge"
        )
        if not success:
            print(f"⚠️  Failed to install {package} via conda, will try pip later")
    
    # Install pip packages
    print("\n📦 Installing packages via pip...")
    for package in pip_packages:
        success = run_command(
            f"pip install {package}",
            f"Installing {package} via pip"
        )
        if not success:
            print(f"❌ Failed to install {package} via pip")
    
    print("\n" + "=" * 50)
    print("✅ Package installation completed!")
    print("\nNext steps:")
    print("1. Copy env.example to .env and set your POLYGON_API_KEY")
    print("2. Run: python src/data_collectors/polygon/launch.py")

if __name__ == "__main__":
    install_packages()
