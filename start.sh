#!/bin/bash

# ============================================
# AI-Powered Log Analyzer - Startup Script
# ============================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║     AI-Powered Log Analyzer & Incident Memory System       ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is required but not installed.${NC}"
    exit 1
fi

# Check for environment file
if [ ! -f "backend/.env" ]; then
    echo -e "${YELLOW}No .env file found. Creating from template...${NC}"
    cp backend/.env.example backend/.env
    echo -e "${YELLOW}Please edit backend/.env and add your API keys.${NC}"
    echo ""
fi

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo -e "${BLUE}Creating Python virtual environment...${NC}"
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo -e "${BLUE}Installing Python dependencies...${NC}"
pip install -q -r backend/requirements.txt

# Create data directories
mkdir -p backend/data/chromadb

# Check for API keys
source backend/.env 2>/dev/null || true

if [ -z "$OPENAI_API_KEY" ] && [ -z "$ANTHROPIC_API_KEY" ]; then
    echo -e "${YELLOW}"
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║  WARNING: No API keys configured!                         ║"
    echo "║                                                            ║"
    echo "║  Please set your API key in backend/.env:                 ║"
    echo "║  - OPENAI_API_KEY=your-key-here                           ║"
    echo "║  OR                                                        ║"
    echo "║  - ANTHROPIC_API_KEY=your-key-here                        ║"
    echo "║                                                            ║"
    echo "║  The app will start but analysis won't work without keys. ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
fi

echo ""
echo -e "${GREEN}Starting services...${NC}"
echo ""

# Start backend in background
echo -e "${BLUE}Starting Backend API on http://localhost:8000${NC}"
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
cd ..

# Wait for backend to start
sleep 2

# Start frontend server
echo -e "${BLUE}Starting Frontend on http://localhost:3000${NC}"
cd frontend
python3 -m http.server 3000 &
FRONTEND_PID=$!
cd ..

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Log Analyzer is running!                                  ║${NC}"
echo -e "${GREEN}║                                                            ║${NC}"
echo -e "${GREEN}║  🌐 Frontend:  http://localhost:3000                       ║${NC}"
echo -e "${GREEN}║  🔧 API:       http://localhost:8000                       ║${NC}"
echo -e "${GREEN}║  📚 API Docs:  http://localhost:8000/docs                  ║${NC}"
echo -e "${GREEN}║                                                            ║${NC}"
echo -e "${GREEN}║  Press Ctrl+C to stop all services                        ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Trap Ctrl+C and cleanup
cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down services...${NC}"
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    echo -e "${GREEN}Goodbye!${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Wait for processes
wait
