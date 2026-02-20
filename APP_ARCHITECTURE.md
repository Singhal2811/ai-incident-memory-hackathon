# AI-Powered Log Analyzer & Organizational Incident Memory
## Architecture & Code Flow Documentation

This document provides a comprehensive overview of the application's architecture and code flow. It is designed to act as a definitive guide for you, your team, and to serve as reference material for your hackathon demo.

---

### 1. High-Level Architecture Overview

The system is a fully dockerized application utilizing an API-driven frontend and an intelligent, multi-agent backend. It bridges the gap between raw log streams and actionable engineering context through AI models.

**Core Services Ecosystem:**
1. **Frontend UI (Nginx + React SPA)**: A minimal reliance, single-page application built with React and Babel compiled in the browser for extreme simplicity. Runs natively on Nginx at port `3000`.
2. **Backend API (FastAPI + Python)**: The brain of the operation. Running on port `8000`, this exposes HTTP endpoints that coordinate large-scale log analysis using intelligent LLM Agents.
3. **Log Storage Engine (VictoriaLogs)**: A high-performance telemetry storage database built by VictoriaMetrics, designed specifically for LogsQL querying. Available on port `9428`.
4. **Vector Memory Database (ChromaDB)**: A persistent semantic search engine integrated within the Python backend, allowing the system to query past incidents using vector embeddings and store generated context.

---

### 2. Backend Architecture (FastAPI & Agents)

The backend (`backend/main.py`) acts as an autonomous investigation pipeline structured around an **Orchestrator Pattern**. 

#### 🧩 Key System Components
* **LLM Client (`LLMClient`)**: A robust, universal wrapper supporting routing to either **OpenAI** (e.g., `gpt-4-turbo-preview`) or **Anthropic** (e.g., `claude-3-opus`). It supports asynchronous requests, auto-retries, exponential backoff, and embedding generation.
* **Log Pre-Processor (`LogPreProcessor`)**: Logs are notoriously verbose. Before passing them to an LLM token window, this utility compresses the logs. It heavily leverages RegEx to detect structures (Tracebacks, Timestamps, JSON) and normalizes identical events by keeping only frequency counters—an approach directly inspired by VictoriaLogs deduplication.
* **Vector Database Wrapper (`IncidentMemory`)**: Uses ChromaDB to parse and query historical incidents via semantic similarity (e.g., "Find times when payment gateway timed out").

#### 🤖 Investigation Agents Pipeline
The orchestration layer sequentially passes data and context state between specialized **Agents**:

1. **`LogAnalysisAgent`**: Analyzes the raw/condensed logs to find anomalies, specific errors, correlations, and outliers. Extracts root cause hypotheses.
2. **`CodeContextAgent`**: Operates on the hypothesis output to examine if recent code changes reflect the errors identified (checks GitHub issue context, code patterns).
3. **`TimelineAgent`**: Synthesizes the parsed timestamps and creates a firm chronological sequence of events tracing back from the incident escalation to root onset.
4. **`RecommendationAgent`**: Leverages the analysis to offer actionable remediation suggestions based on engineering best practices and historical data context.
5. **`PIRGeneratorAgent`**: Synthesizes output from all prior agents into a single, comprehensive Post-Incident Review (PIR) document containing blast radiuses, summaries, and action items.

#### 🔄 Backend Execution Flow (The API Endpoint)
When a user submits logs `/api/v1/analyze`:
1. **Intake**: Endpoint receives `IncidentAnalysisRequest` containing form data, log queries, or raw log files.
2. **Data Fetch**: Queries VictoriaLogs (if configured) or captures raw uploaded logs.
3. **Pre-Processing**: The raw text flows into the `LogPreProcessor`, outputting a condensed summary with stats and deduplicated errors.
4. **Agent Orchestration**: `AgentOrchestrator.investigate()` boots up the agents. Context builds dynamically: The `LogAnalysisAgent` executes first, then passes context to the `TimelineAgent`, and so forth.
5. **Memory Lookup**: While processing, `IncidentMemory` searches ChromaDB to append similar past incidents to the context. 
6. **Result Storage**: Upon successful agent pipeline completion, the final report is stored back into `IncidentMemory` as embeddings.
7. **Response Delivery**: JSON object constructed under `AnalysisResult` is fed back to the client.

---

### 3. Frontend Architecture (React SPA)

The frontend (`frontend/index.html`) is designed to look like a fully fledged React platform but executes within a single `index.html` structure (via babel-standalone) for maximum hackathon portability. 

#### 🧩 Key React Components
* **`App`**: Top-level State Management. Manages current views (analyze vs. memory), handles global fetching states, and renders modals.
* **`Sidebar` & `Header`**: Navigation elements to toggle between "Analyze Logs", "Incident Memory", and viewing the AI Provider's API health checks and configuration (`ConfigModal`).
* **`LogAnalysisForm`**: Dynamic intelligent form for intake. Supports copy-paste logs, raw `.log` file uploads, ZIP file batch uploads, or querying direct from VictoriaLogs using LogsQL.
* **`LoadingOverlay`**: Handles the UX portion of waiting for AI API completion. Continuously polls or simulates the transition between agent steps to give users a sense of fluid backend progress.
* **`AnalysisResults`**: A robust tabbed interface that digests the backend `AnalysisResult`. It partitions the view cleanly into: Overview, Agent JSONs, Timeline Graph, Similarity Search hits, and PIR Document Markdown.

#### 🔄 Frontend User Flow
1. User configures API Keys (OpenAI/Anthropic) via the Top Header Modal.
2. User submits escalation context via the `LogAnalysisForm` component (Uploads a raw `.zip` of stack traces and logs).
3. The frontend triggers the backend `POST /api/v1/analyze/zip` maintaining a loading state. 
4. Upon resolution, it mounts `AnalysisResults`, unpacking the nested JSON into stylized React tags, rendering interactive `.PIR` reports and mapping `Timeline` dictionaries.

---

