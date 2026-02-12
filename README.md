# 🔍 AI-Powered Log Analyzer & Organizational Incident Memory

A sophisticated incident investigation platform that transforms raw logs into reusable operational intelligence using AI agents and vector-based organizational memory.

![Log Analyzer](https://img.shields.io/badge/Status-Production_Ready-green)
![Python](https://img.shields.io/badge/Python-3.11+-blue)
![License](https://img.shields.io/badge/License-MIT-yellow)

## 🌟 Features

### Core Capabilities

- **🔬 AI-Powered Log Analysis** - Automatically detect anomalies, error patterns, and correlations
- **🧠 Organizational Incident Memory** - Vector database that learns from every incident
- **⏱️ Automated Timeline Generation** - Build chronological incident timelines automatically
- **🔗 Code Context Correlation** - Link log errors to recent code changes
- **📊 Similar Incident Search** - Find and learn from past incidents
- **📄 PIR Generation** - Auto-generate Post-Incident Review documents
- **💡 AI Recommendations** - Get actionable remediation suggestions

### Investigation Agents

| Agent | Purpose |
|-------|---------|
| **Log Analysis Agent** | Detects anomalies, error patterns, and correlations |
| **Code Context Agent** | Links anomalies to recent code changes |
| **Timeline Agent** | Builds chronological incident timeline |
| **Recommendation Agent** | Suggests actions based on historical data |
| **PIR Generator Agent** | Creates Post-Incident Review documents |

## 🚀 Quick Start

### Option 1: Local Development

```bash
# Clone and navigate to the project
cd log-analyzer

# Copy environment template and add your API keys
cp backend/.env.example backend/.env
# Edit backend/.env and add your API keys

# Start the application
chmod +x start.sh
./start.sh
```

### Option 2: Docker Compose

```bash
# Set your API keys
export OPENAI_API_KEY=your-openai-key
# OR
export ANTHROPIC_API_KEY=your-anthropic-key

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f
```

### Access Points

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Documentation | http://localhost:8000/docs |
| VictoriaLogs | http://localhost:9428 |

## ⚙️ Configuration

### Environment Variables

Create a `.env` file in the `backend/` directory:

```env
# LLM Provider (choose one)
LLM_PROVIDER=openai  # or "anthropic"

# OpenAI Configuration
OPENAI_API_KEY=sk-your-openai-key-here
OPENAI_MODEL=gpt-4-turbo-preview

# Anthropic Configuration  
ANTHROPIC_API_KEY=your-anthropic-key-here
ANTHROPIC_MODEL=claude-3-opus-20240229

# VictoriaLogs (optional - for production log ingestion)
VICTORIALOGS_URL=http://localhost:9428

# Vector Database
CHROMA_PERSIST_DIR=./data/chromadb
```

## 📖 API Reference

### Analyze Incident

```bash
POST /api/v1/analyze

{
  "escalation": {
    "service": "payment-service",
    "severity": "P1",
    "summary": "Payment gateway timeout",
    "start_time": "2024-01-15T10:23:00Z"
  },
  "raw_logs": "... your logs here ...",
  "include_similar": true,
  "generate_pir": true
}
```

### Search Similar Incidents

```bash
POST /api/v1/search-similar

{
  "query": "database connection timeout",
  "top_k": 5,
  "filter_service": "api-gateway"
}
```

### Upload Log File

```bash
POST /api/v1/upload-logs

# Form data:
# - file: (log file)
# - service: payment-service
# - severity: P2
# - summary: Error investigation
```

### Demo Logs

```bash
GET /api/v1/demo-logs
# Returns sample logs for testing
```

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (React)                        │
│                    http://localhost:3000                     │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                   Backend API (FastAPI)                      │
│                    http://localhost:8000                     │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Agent Orchestrator                      │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐            │    │
│  │  │   Log    │ │  Code    │ │ Timeline │            │    │
│  │  │ Analysis │ │ Context  │ │  Agent   │            │    │
│  │  └──────────┘ └──────────┘ └──────────┘            │    │
│  │  ┌──────────┐ ┌──────────┐                          │    │
│  │  │  Recom-  │ │   PIR    │                          │    │
│  │  │ mendation│ │Generator │                          │    │
│  │  └──────────┘ └──────────┘                          │    │
│  └─────────────────────────────────────────────────────┘    │
└────────────┬──────────────────────────┬─────────────────────┘
             │                          │
┌────────────▼────────────┐  ┌──────────▼──────────────────────┐
│    VictoriaLogs         │  │        ChromaDB                 │
│  (Log Storage/Query)    │  │   (Incident Memory)             │
│  http://localhost:9428  │  │   Vector Embeddings             │
└─────────────────────────┘  └─────────────────────────────────┘
```

## 💡 Usage Examples

### Analyzing Production Logs

1. Navigate to **Analyze Logs** in the sidebar
2. Enter incident details (service, severity, summary)
3. Paste your logs or use the demo data
4. Click **Analyze Incident**
5. Review results across tabs: Overview, Agents, Timeline, Similar Incidents, PIR

### Searching Incident Memory

1. Navigate to **Incident Memory** in the sidebar
2. Enter a search query (e.g., "database connection pool exhausted")
3. Review similar past incidents
4. Learn from previous root causes and resolutions

### Uploading Log Files

1. Navigate to **Upload Logs** in the sidebar
2. Drag and drop your `.log`, `.txt`, or `.json` file
3. Fill in service details
4. Click **Analyze File**

## 🔧 Development

### Project Structure

```
log-analyzer/
├── backend/
│   ├── main.py           # FastAPI application & agents
│   ├── requirements.txt  # Python dependencies
│   ├── Dockerfile        # Backend container
│   └── .env.example      # Environment template
├── frontend/
│   └── index.html        # React SPA
├── docker-compose.yml    # Full stack deployment
├── start.sh              # Local development script
└── README.md             # This file
```

### Adding New Agents

1. Create a new agent class extending `BaseAgent`
2. Implement the `execute()` method
3. Add to `AgentOrchestrator.agents` dictionary
4. Wire into the investigation pipeline

```python
class MyCustomAgent(BaseAgent):
    def __init__(self, llm: LLMClient):
        super().__init__("My Custom Agent", llm)
    
    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        # Your agent logic here
        return {"result": "..."}
```

## 🔐 Security Notes

- API keys are stored locally in `.env` files
- Never commit `.env` files to version control
- Use environment variables in production
- VictoriaLogs access should be restricted in production

## 🛣️ Roadmap

- [ ] Slack / PagerDuty integration
- [ ] Real-time log streaming analysis
- [ ] Metrics + logs correlation (VictoriaMetrics)
- [ ] Automated blast radius prediction
- [ ] Feedback loop for recommendation improvement
- [ ] Multi-tenant support
- [ ] SSO integration

## 📄 License

MIT License - See LICENSE file for details.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

---

Built with ❤️ using FastAPI, React, ChromaDB, and VictoriaLogs
