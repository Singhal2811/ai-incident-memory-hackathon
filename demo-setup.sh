#!/bin/bash

# ============================================
# Quick Demo Setup Script
# ============================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🚀 AI-Powered Log Analyzer - Quick Demo Setup"
echo ""

# Check for .env file
if [ ! -f "backend/.env" ]; then
    echo "📝 Creating .env file from template..."
    cp backend/.env.example backend/.env
    echo ""
    echo "⚠️  IMPORTANT: Please edit backend/.env and add your API key:"
    echo "   - For OpenAI: Add OPENAI_API_KEY"
    echo "   - For Anthropic: Add ANTHROPIC_API_KEY"
    echo ""
    read -p "Press ENTER after you've added your API key..."
fi

# Check if API key is configured
source backend/.env 2>/dev/null || true
if [ -z "$OPENAI_API_KEY" ] && [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "❌ ERROR: No API key found in backend/.env"
    echo "Please add either OPENAI_API_KEY or ANTHROPIC_API_KEY"
    exit 1
fi

echo "✅ API key configured!"
echo ""

# Create virtual environment if doesn't exist
if [ ! -d "venv" ]; then
    echo "📦 Creating Python virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r backend/requirements.txt

# Create data directories
mkdir -p backend/data/chromadb

echo ""
echo "✅ Setup complete!"
echo ""
echo "👉 To start the demo:"
echo "   1. Run: ./start.sh"
echo "   2. Open: http://localhost:3000"
echo "   3. Try the demo scenarios from the sidebar"
echo ""
echo "📊 Demo Scenarios Available:"
echo "   - Payment Gateway Timeout"
echo "   - Database Pool Exhaustion"
echo "   - Memory Leak Detection"
echo ""
