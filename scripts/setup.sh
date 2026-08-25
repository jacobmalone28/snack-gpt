#!/bin/bash
set -e

echo "Setting up Snack GPT..."

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3.11 -m venv venv || python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip setuptools wheel

# Install dependencies
echo "Installing dependencies..."
pip install -e ".[dev]"

# Create necessary directories
mkdir -p data logs

# Initialize or upgrade the database
echo "Initializing database..."
alembic upgrade head

echo "Setup complete!"
echo "To activate the environment, run: source venv/bin/activate"
