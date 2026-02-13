"""
AI-Powered Log Analyzer & Organizational Incident Memory
Main Application Entry Point
"""

import os
import json
import asyncio
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import httpx
import chromadb
from chromadb.config import Settings

# Load environment variables
load_dotenv()

# =============================================================================
# Configuration
# =============================================================================

class Config:
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4-turbo-preview")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-opus-20240229")
    VICTORIALOGS_URL = os.getenv("VICTORIALOGS_URL", "http://localhost:9428")
    CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./data/chromadb")
    CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "incident_memory")

# =============================================================================
# Pydantic Models
# =============================================================================

class LogQuery(BaseModel):
    query: str = Field(..., description="LogsQL query string")
    start_time: Optional[str] = Field(None, description="Start time (ISO format or relative like -1h)")
    end_time: Optional[str] = Field(None, description="End time (ISO format or relative)")
    limit: int = Field(1000, description="Maximum number of log lines to return")

class EscalationDetails(BaseModel):
    service: str = Field(..., description="Affected service name")
    severity: str = Field(..., description="Incident severity (P1-P4)")
    summary: str = Field(..., description="Brief incident summary")
    start_time: str = Field(..., description="When the incident started")
    end_time: Optional[str] = Field(None, description="When the incident ended")
    reported_by: Optional[str] = Field(None, description="Who reported the incident")
    ticket_id: Optional[str] = Field(None, description="Associated ticket ID")

class IncidentAnalysisRequest(BaseModel):
    escalation: EscalationDetails
    log_query: Optional[LogQuery] = None
    raw_logs: Optional[str] = Field(None, description="Raw log text if not using VictoriaLogs")
    git_repo_url: Optional[str] = Field(None, description="Git repository URL for code context")
    include_similar: bool = Field(True, description="Search for similar past incidents")
    generate_pir: bool = Field(True, description="Generate Post-Incident Review")

class SimilaritySearchRequest(BaseModel):
    query: str = Field(..., description="Search query for finding similar incidents")
    top_k: int = Field(5, description="Number of results to return")
    filter_service: Optional[str] = Field(None, description="Filter by service name")

class IncidentSummary(BaseModel):
    incident_id: str
    service: str
    severity: str
    summary: str
    root_cause: Optional[str]
    resolution: Optional[str]
    timestamp: str
    similarity_score: Optional[float] = None

class AgentResponse(BaseModel):
    agent_name: str
    status: str
    output: Dict[str, Any]
    execution_time: float

class AnalysisResult(BaseModel):
    incident_id: str
    status: str
    escalation: EscalationDetails
    agents: List[AgentResponse]
    timeline: List[Dict[str, Any]]
    similar_incidents: List[IncidentSummary]
    recommendations: List[str]
    pir: Optional[str]
    created_at: str

# =============================================================================
# LLM Client
# =============================================================================

class LLMClient:
    """Unified LLM client supporting OpenAI and Anthropic"""
    
    def __init__(self):
        self.provider = Config.LLM_PROVIDER
        self.http_client = httpx.AsyncClient(timeout=120.0)
    
    async def complete(self, messages: List[Dict[str, str]], system: str = None, temperature: float = 0.3) -> str:
        if self.provider == "anthropic":
            return await self._anthropic_complete(messages, system, temperature)
        else:
            return await self._openai_complete(messages, system, temperature)
    
    async def _openai_complete(self, messages: List[Dict[str, str]], system: str, temperature: float) -> str:
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)
        
        response = await self.http_client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {Config.OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": Config.OPENAI_MODEL,
                "messages": all_messages,
                "temperature": temperature,
                "max_tokens": 4096
            }
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    
    async def _anthropic_complete(self, messages: List[Dict[str, str]], system: str, temperature: float) -> str:
        response = await self.http_client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": Config.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            },
            json={
                "model": Config.ANTHROPIC_MODEL,
                "max_tokens": 4096,
                "system": system or "You are a helpful assistant.",
                "messages": messages,
                "temperature": temperature
            }
        )
        response.raise_for_status()
        return response.json()["content"][0]["text"]
    
    async def get_embedding(self, text: str) -> List[float]:
        """Get text embedding - uses OpenAI if available, otherwise hash-based fallback"""
        if Config.OPENAI_API_KEY:
            response = await self.http_client.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {Config.OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "text-embedding-3-small",
                    "input": text
                }
            )
            response.raise_for_status()
            return response.json()["data"][0]["embedding"]
        else:
            # Hash-based embedding fallback when no OpenAI key is available
            import struct
            embedding_dim = 384
            embedding = []
            for i in range(embedding_dim):
                h = hashlib.md5(f"{text}_{i}".encode()).digest()
                val = struct.unpack('f', bytes(h[0:4]))[0]
                # Normalize to [-1, 1]
                val = (val % 2) - 1
                embedding.append(val)
            # L2 normalize
            norm = sum(v*v for v in embedding) ** 0.5
            if norm > 0:
                embedding = [v / norm for v in embedding]
            return embedding

# =============================================================================
# VictoriaLogs Client
# =============================================================================

class VictoriaLogsClient:
    """Client for querying VictoriaLogs"""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or Config.VICTORIALOGS_URL
        self.http_client = httpx.AsyncClient(timeout=30.0)
    
    async def query(self, query: str, start: str = None, end: str = None, limit: int = 1000) -> List[Dict]:
        """Execute a LogsQL query"""
        params = {"query": query, "limit": limit}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        
        try:
            response = await self.http_client.get(
                f"{self.base_url}/select/logsql/query",
                params=params
            )
            response.raise_for_status()
            
            # Parse JSONL response
            logs = []
            for line in response.text.strip().split('\n'):
                if line:
                    logs.append(json.loads(line))
            return logs
        except httpx.ConnectError:
            # VictoriaLogs not available - return empty
            return []
        except Exception as e:
            print(f"VictoriaLogs query error: {e}")
            return []
    
    async def health_check(self) -> bool:
        """Check if VictoriaLogs is available"""
        try:
            response = await self.http_client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except:
            return False

# =============================================================================
# Vector Database (Incident Memory)
# =============================================================================

class IncidentMemory:
    """Vector database for storing and retrieving incident knowledge"""
    
    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=Config.CHROMA_PERSIST_DIR,
            settings=Settings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection(
            name=Config.CHROMA_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
        self.llm = LLMClient()
    
    async def store_incident(self, incident_id: str, incident_data: Dict[str, Any]):
        """Store incident in vector database"""
        # Create searchable text from incident data
        text = self._create_incident_text(incident_data)
        
        # Get embedding
        embedding = await self.llm.get_embedding(text)
        
        # Store in ChromaDB
        self.collection.add(
            ids=[incident_id],
            embeddings=[embedding],
            metadatas=[{
                "service": incident_data.get("service", ""),
                "severity": incident_data.get("severity", ""),
                "timestamp": incident_data.get("timestamp", ""),
                "root_cause": incident_data.get("root_cause", ""),
                "resolution": incident_data.get("resolution", "")
            }],
            documents=[text]
        )
    
    async def search_similar(self, query: str, top_k: int = 5, filter_service: str = None) -> List[Dict]:
        """Search for similar incidents"""
        embedding = await self.llm.get_embedding(query)
        
        where_filter = None
        if filter_service:
            where_filter = {"service": filter_service}
        
        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            where=where_filter,
            include=["documents", "metadatas", "distances"]
        )
        
        incidents = []
        if results["ids"] and results["ids"][0]:
            for i, incident_id in enumerate(results["ids"][0]):
                incidents.append({
                    "incident_id": incident_id,
                    "text": results["documents"][0][i] if results["documents"] else "",
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "similarity": 1 - results["distances"][0][i] if results["distances"] else 0
                })
        
        return incidents
    
    def _create_incident_text(self, data: Dict) -> str:
        """Create searchable text from incident data"""
        parts = [
            f"Service: {data.get('service', 'unknown')}",
            f"Severity: {data.get('severity', 'unknown')}",
            f"Summary: {data.get('summary', '')}",
            f"Root Cause: {data.get('root_cause', '')}",
            f"Resolution: {data.get('resolution', '')}",
            f"Timeline: {data.get('timeline', '')}",
        ]
        return "\n".join(parts)

# =============================================================================
# Investigation Agents
# =============================================================================

class BaseAgent:
    """Base class for all investigation agents"""
    
    def __init__(self, name: str, llm: LLMClient):
        self.name = name
        self.llm = llm
    
    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class LogAnalysisAgent(BaseAgent):
    """Analyzes logs to detect anomalies, patterns, and correlations"""
    
    def __init__(self, llm: LLMClient):
        super().__init__("Log Analysis Agent", llm)
    
    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        logs = context.get("logs", "")
        escalation = context.get("escalation", {})
        
        system_prompt = """You are an expert log analyst specializing in production incident investigation.
Your task is to analyze log data and identify:
1. Error patterns and anomalies
2. Correlation between events
3. Potential root causes
4. Timeline of events leading to the incident

Provide your analysis in a structured JSON format with the following keys:
- errors: List of unique errors found
- patterns: Recurring patterns identified
- anomalies: Unusual behaviors detected
- correlations: Relationships between events
- potential_causes: Ranked list of potential root causes
- key_timestamps: Important timestamps in the incident timeline"""

        user_message = f"""Analyze the following logs for incident investigation:

Incident Summary: {escalation.get('summary', 'N/A')}
Service: {escalation.get('service', 'N/A')}
Severity: {escalation.get('severity', 'N/A')}
Start Time: {escalation.get('start_time', 'N/A')}

=== LOGS ===
{logs[:50000]}  # Truncate to fit context
"""

        response = await self.llm.complete(
            messages=[{"role": "user", "content": user_message}],
            system=system_prompt,
            temperature=0.2
        )
        
        try:
            # Try to parse JSON from response
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                return json.loads(response[json_start:json_end])
        except json.JSONDecodeError:
            pass
        
        return {"raw_analysis": response}


class CodeContextAgent(BaseAgent):
    """Links log anomalies to recent code changes"""
    
    def __init__(self, llm: LLMClient):
        super().__init__("Code Context Agent", llm)
    
    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        log_analysis = context.get("log_analysis", {})
        git_info = context.get("git_info", {})
        escalation = context.get("escalation", {})
        
        system_prompt = """You are a senior software engineer investigating production incidents.
Your task is to correlate log errors with recent code changes to identify if any recent deployments caused the issue.

Analyze the relationship between:
1. Errors and anomalies found in logs
2. Recent code commits and changes
3. Deployment timeline

Provide your analysis in JSON format with:
- suspected_commits: List of commits that might have caused the issue
- code_areas: Areas of code likely involved
- deployment_correlation: Whether the incident correlates with recent deployments
- confidence: Your confidence level (high/medium/low)
- reasoning: Explanation of your analysis"""

        user_message = f"""Correlate log analysis with code changes:

Log Analysis:
{json.dumps(log_analysis, indent=2)}

Recent Git Activity:
{json.dumps(git_info, indent=2)}

Incident:
Service: {escalation.get('service', 'N/A')}
Start Time: {escalation.get('start_time', 'N/A')}
"""

        response = await self.llm.complete(
            messages=[{"role": "user", "content": user_message}],
            system=system_prompt,
            temperature=0.2
        )
        
        try:
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                return json.loads(response[json_start:json_end])
        except json.JSONDecodeError:
            pass
        
        return {"raw_analysis": response}


class TimelineAgent(BaseAgent):
    """Builds a chronological incident timeline"""
    
    def __init__(self, llm: LLMClient):
        super().__init__("Timeline Agent", llm)
    
    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        log_analysis = context.get("log_analysis", {})
        escalation = context.get("escalation", {})
        
        system_prompt = """You are an incident timeline specialist.
Create a precise chronological timeline of the incident from the available information.

For each event in the timeline, include:
- timestamp: When it occurred
- event: What happened
- impact: What was affected
- source: Where this information came from (logs, alerts, etc.)

Return a JSON object with:
- timeline: Array of events in chronological order
- duration_estimate: Estimated total incident duration
- phases: Key phases of the incident (detection, impact, mitigation, resolution)"""

        user_message = f"""Build an incident timeline from:

Incident Details:
Service: {escalation.get('service', 'N/A')}
Start Time: {escalation.get('start_time', 'N/A')}
End Time: {escalation.get('end_time', 'N/A')}
Summary: {escalation.get('summary', 'N/A')}

Log Analysis:
{json.dumps(log_analysis, indent=2)}
"""

        response = await self.llm.complete(
            messages=[{"role": "user", "content": user_message}],
            system=system_prompt,
            temperature=0.2
        )
        
        try:
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                return json.loads(response[json_start:json_end])
        except json.JSONDecodeError:
            pass
        
        return {"raw_timeline": response}


class RecommendationAgent(BaseAgent):
    """Suggests next actions based on analysis and historical data"""
    
    def __init__(self, llm: LLMClient):
        super().__init__("Recommendation Agent", llm)
    
    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        log_analysis = context.get("log_analysis", {})
        code_context = context.get("code_context", {})
        similar_incidents = context.get("similar_incidents", [])
        escalation = context.get("escalation", {})
        
        system_prompt = """You are an SRE expert providing actionable recommendations for incident resolution.

Based on the analysis and similar past incidents, provide:
1. Immediate actions to mitigate the incident
2. Investigation steps to confirm root cause
3. Long-term fixes to prevent recurrence
4. Monitoring improvements needed

Return JSON with:
- immediate_actions: Prioritized list of immediate steps
- investigation_steps: Steps to confirm root cause
- permanent_fixes: Long-term solutions
- monitoring_improvements: Suggested monitoring/alerting changes
- estimated_resolution_time: Estimate based on similar incidents"""

        similar_text = ""
        for inc in similar_incidents[:3]:
            similar_text += f"\n- {inc.get('metadata', {}).get('service')}: {inc.get('text', '')[:500]}"
        
        user_message = f"""Provide recommendations for:

Current Incident:
Service: {escalation.get('service', 'N/A')}
Severity: {escalation.get('severity', 'N/A')}
Summary: {escalation.get('summary', 'N/A')}

Log Analysis:
{json.dumps(log_analysis, indent=2)}

Code Context:
{json.dumps(code_context, indent=2)}

Similar Past Incidents:{similar_text if similar_text else " None found"}
"""

        response = await self.llm.complete(
            messages=[{"role": "user", "content": user_message}],
            system=system_prompt,
            temperature=0.3
        )
        
        try:
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                return json.loads(response[json_start:json_end])
        except json.JSONDecodeError:
            pass
        
        return {"raw_recommendations": response}


class PIRGeneratorAgent(BaseAgent):
    """Generates comprehensive Post-Incident Review documents"""
    
    def __init__(self, llm: LLMClient):
        super().__init__("PIR Generator Agent", llm)
    
    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        escalation = context.get("escalation", {})
        log_analysis = context.get("log_analysis", {})
        timeline = context.get("timeline", {})
        recommendations = context.get("recommendations", {})
        
        system_prompt = """You are a technical writer specializing in Post-Incident Reviews (PIRs).
Create a comprehensive, blameless PIR document that can be shared with stakeholders.

The PIR should include:
1. Executive Summary
2. Incident Timeline
3. Impact Assessment
4. Root Cause Analysis
5. What Went Well
6. What Needs Improvement
7. Action Items (with owners and due dates)
8. Appendix (key metrics, logs snippets)

Write in clear, professional prose. Focus on learning, not blame."""

        user_message = f"""Generate a Post-Incident Review for:

Incident Details:
- Service: {escalation.get('service', 'N/A')}
- Severity: {escalation.get('severity', 'N/A')}
- Summary: {escalation.get('summary', 'N/A')}
- Duration: {escalation.get('start_time', 'N/A')} to {escalation.get('end_time', 'N/A')}
- Reported By: {escalation.get('reported_by', 'N/A')}
- Ticket: {escalation.get('ticket_id', 'N/A')}

Log Analysis:
{json.dumps(log_analysis, indent=2)}

Timeline:
{json.dumps(timeline, indent=2)}

Recommendations:
{json.dumps(recommendations, indent=2)}
"""

        response = await self.llm.complete(
            messages=[{"role": "user", "content": user_message}],
            system=system_prompt,
            temperature=0.4
        )
        
        return {"pir_document": response}

# =============================================================================
# Agent Orchestrator
# =============================================================================

class AgentOrchestrator:
    """Coordinates all investigation agents"""
    
    def __init__(self):
        self.llm = LLMClient()
        self.victoria_logs = VictoriaLogsClient()
        self.incident_memory = IncidentMemory()
        
        # Initialize agents
        self.agents = {
            "log_analysis": LogAnalysisAgent(self.llm),
            "code_context": CodeContextAgent(self.llm),
            "timeline": TimelineAgent(self.llm),
            "recommendation": RecommendationAgent(self.llm),
            "pir_generator": PIRGeneratorAgent(self.llm)
        }
    
    async def investigate(self, request: IncidentAnalysisRequest) -> AnalysisResult:
        """Run full incident investigation"""
        start_time = datetime.now()
        incident_id = self._generate_incident_id(request)
        
        context = {
            "escalation": request.escalation.model_dump(),
            "logs": "",
            "git_info": {},
            "log_analysis": {},
            "code_context": {},
            "timeline": {},
            "recommendations": {},
            "similar_incidents": []
        }
        
        agent_responses = []
        
        # Step 1: Fetch logs
        if request.raw_logs:
            context["logs"] = request.raw_logs
        elif request.log_query:
            logs = await self.victoria_logs.query(
                query=request.log_query.query,
                start=request.log_query.start_time,
                end=request.log_query.end_time,
                limit=request.log_query.limit
            )
            context["logs"] = "\n".join([json.dumps(log) for log in logs])
        
        # Step 2: Find similar incidents
        if request.include_similar:
            search_query = f"{request.escalation.service} {request.escalation.summary}"
            context["similar_incidents"] = await self.incident_memory.search_similar(search_query)
        
        # Step 3: Run Log Analysis Agent
        agent_start = datetime.now()
        context["log_analysis"] = await self.agents["log_analysis"].execute(context)
        agent_responses.append(AgentResponse(
            agent_name="Log Analysis Agent",
            status="completed",
            output=context["log_analysis"],
            execution_time=(datetime.now() - agent_start).total_seconds()
        ))
        
        # Step 4: Run Code Context Agent
        agent_start = datetime.now()
        context["code_context"] = await self.agents["code_context"].execute(context)
        agent_responses.append(AgentResponse(
            agent_name="Code Context Agent",
            status="completed",
            output=context["code_context"],
            execution_time=(datetime.now() - agent_start).total_seconds()
        ))
        
        # Step 5: Run Timeline Agent
        agent_start = datetime.now()
        context["timeline"] = await self.agents["timeline"].execute(context)
        agent_responses.append(AgentResponse(
            agent_name="Timeline Agent",
            status="completed",
            output=context["timeline"],
            execution_time=(datetime.now() - agent_start).total_seconds()
        ))
        
        # Step 6: Run Recommendation Agent
        agent_start = datetime.now()
        context["recommendations"] = await self.agents["recommendation"].execute(context)
        agent_responses.append(AgentResponse(
            agent_name="Recommendation Agent",
            status="completed",
            output=context["recommendations"],
            execution_time=(datetime.now() - agent_start).total_seconds()
        ))
        
        # Step 7: Generate PIR if requested
        pir_document = None
        if request.generate_pir:
            agent_start = datetime.now()
            pir_result = await self.agents["pir_generator"].execute(context)
            pir_document = pir_result.get("pir_document", "")
            agent_responses.append(AgentResponse(
                agent_name="PIR Generator Agent",
                status="completed",
                output={"pir_generated": True},
                execution_time=(datetime.now() - agent_start).total_seconds()
            ))
        
        # Step 8: Store incident in memory for future reference
        await self.incident_memory.store_incident(incident_id, {
            "service": request.escalation.service,
            "severity": request.escalation.severity,
            "summary": request.escalation.summary,
            "timestamp": request.escalation.start_time,
            "root_cause": context["log_analysis"].get("potential_causes", ["Unknown"])[0] if isinstance(context["log_analysis"].get("potential_causes"), list) else "Unknown",
            "resolution": json.dumps(context["recommendations"].get("immediate_actions", [])),
            "timeline": json.dumps(context["timeline"])
        })
        
        # Build timeline from analysis
        timeline_events = context["timeline"].get("timeline", [])
        if isinstance(timeline_events, str):
            timeline_events = []
        
        # Build similar incidents list
        similar = [
            IncidentSummary(
                incident_id=inc["incident_id"],
                service=inc.get("metadata", {}).get("service", ""),
                severity=inc.get("metadata", {}).get("severity", ""),
                summary=inc.get("text", "")[:200],
                root_cause=inc.get("metadata", {}).get("root_cause"),
                resolution=inc.get("metadata", {}).get("resolution"),
                timestamp=inc.get("metadata", {}).get("timestamp", ""),
                similarity_score=inc.get("similarity", 0)
            )
            for inc in context["similar_incidents"]
        ]
        
        # Build recommendations list
        recommendations = context["recommendations"].get("immediate_actions", [])
        if not isinstance(recommendations, list):
            recommendations = [str(recommendations)]
        
        return AnalysisResult(
            incident_id=incident_id,
            status="completed",
            escalation=request.escalation,
            agents=agent_responses,
            timeline=timeline_events,
            similar_incidents=similar,
            recommendations=recommendations,
            pir=pir_document,
            created_at=datetime.now().isoformat()
        )
    
    def _generate_incident_id(self, request: IncidentAnalysisRequest) -> str:
        """Generate unique incident ID"""
        data = f"{request.escalation.service}-{request.escalation.start_time}-{datetime.now().isoformat()}"
        return f"INC-{hashlib.md5(data.encode()).hexdigest()[:8].upper()}"

# =============================================================================
# FastAPI Application
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("🚀 Starting AI-Powered Log Analyzer")
    app.state.orchestrator = AgentOrchestrator()
    yield
    # Shutdown
    print("👋 Shutting down")

app = FastAPI(
    title="AI-Powered Log Analyzer",
    description="Intelligent incident investigation with organizational memory",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check
@app.get("/health")
async def health_check():
    victoria_healthy = await app.state.orchestrator.victoria_logs.health_check()
    return {
        "status": "healthy",
        "components": {
            "api": True,
            "victoria_logs": victoria_healthy,
            "vector_db": True
        }
    }

# Main investigation endpoint
@app.post("/api/v1/analyze", response_model=AnalysisResult)
async def analyze_incident(request: IncidentAnalysisRequest):
    """
    Analyze an incident using all available agents.
    Supports both VictoriaLogs queries and raw log input.
    """
    try:
        result = await app.state.orchestrator.investigate(request)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Quick log analysis
@app.post("/api/v1/analyze-logs")
async def analyze_logs_quick(
    logs: str = Form(...),
    service: str = Form(...),
    severity: str = Form("P3"),
    summary: str = Form("")
):
    """Quick log analysis without full incident workflow"""
    request = IncidentAnalysisRequest(
        escalation=EscalationDetails(
            service=service,
            severity=severity,
            summary=summary or "Log analysis request",
            start_time=datetime.now().isoformat()
        ),
        raw_logs=logs,
        include_similar=True,
        generate_pir=False
    )
    
    result = await app.state.orchestrator.investigate(request)
    return result

# Upload log file
@app.post("/api/v1/upload-logs")
async def upload_log_file(
    file: UploadFile = File(...),
    service: str = Form(...),
    severity: str = Form("P3"),
    summary: str = Form("")
):
    """Upload a log file for analysis"""
    content = await file.read()
    logs = content.decode('utf-8', errors='ignore')
    
    request = IncidentAnalysisRequest(
        escalation=EscalationDetails(
            service=service,
            severity=severity,
            summary=summary or f"Analysis of {file.filename}",
            start_time=datetime.now().isoformat()
        ),
        raw_logs=logs,
        include_similar=True,
        generate_pir=True
    )
    
    result = await app.state.orchestrator.investigate(request)
    return result

# Search similar incidents
@app.post("/api/v1/search-similar")
async def search_similar_incidents(request: SimilaritySearchRequest):
    """Search for similar past incidents"""
    results = await app.state.orchestrator.incident_memory.search_similar(
        query=request.query,
        top_k=request.top_k,
        filter_service=request.filter_service
    )
    return {"results": results}

# Query VictoriaLogs directly
@app.post("/api/v1/query-logs")
async def query_victoria_logs(query: LogQuery):
    """Execute a LogsQL query against VictoriaLogs"""
    logs = await app.state.orchestrator.victoria_logs.query(
        query=query.query,
        start=query.start_time,
        end=query.end_time,
        limit=query.limit
    )
    return {"logs": logs, "count": len(logs)}

# Generate PIR only
@app.post("/api/v1/generate-pir")
async def generate_pir(
    incident_id: str = Form(...),
    service: str = Form(...),
    severity: str = Form(...),
    summary: str = Form(...),
    root_cause: str = Form(...),
    resolution: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(None)
):
    """Generate a PIR document from incident details"""
    context = {
        "escalation": {
            "service": service,
            "severity": severity,
            "summary": summary,
            "start_time": start_time,
            "end_time": end_time
        },
        "log_analysis": {"potential_causes": [root_cause]},
        "timeline": {},
        "recommendations": {"immediate_actions": [resolution]}
    }
    
    pir_agent = PIRGeneratorAgent(app.state.orchestrator.llm)
    result = await pir_agent.execute(context)
    
    return {"incident_id": incident_id, "pir": result.get("pir_document", "")}

# Demo data endpoint (for testing without VictoriaLogs)
@app.get("/api/v1/demo-logs")
async def get_demo_logs():
    """Get sample logs for testing"""
    demo_logs = """2024-01-15 10:23:45.123 ERROR [payment-service] PaymentProcessor - Connection timeout to payment gateway after 30000ms
2024-01-15 10:23:45.234 WARN [payment-service] CircuitBreaker - Circuit breaker OPEN for payment-gateway, failures: 5
2024-01-15 10:23:46.001 ERROR [payment-service] PaymentProcessor - Failed to process payment: java.net.SocketTimeoutException: connect timed out
2024-01-15 10:23:46.123 INFO [payment-service] RetryHandler - Retrying payment processing, attempt 2 of 3
2024-01-15 10:23:47.234 ERROR [payment-service] PaymentProcessor - Connection timeout to payment gateway after 30000ms
2024-01-15 10:23:47.345 ERROR [payment-service] PaymentProcessor - All retry attempts exhausted
2024-01-15 10:23:47.456 ERROR [order-service] OrderManager - Payment failed for order ORD-12345: PAYMENT_GATEWAY_TIMEOUT
2024-01-15 10:23:48.001 WARN [order-service] OrderManager - Marking order ORD-12345 as PAYMENT_PENDING
2024-01-15 10:23:48.234 ERROR [api-gateway] RequestHandler - 504 Gateway Timeout for POST /api/v1/payments
2024-01-15 10:23:49.001 WARN [monitoring] AlertManager - High error rate detected on payment-service: 45% (threshold: 10%)
2024-01-15 10:23:50.123 INFO [payment-service] HealthCheck - Database connection: OK
2024-01-15 10:23:50.234 ERROR [payment-service] HealthCheck - External dependency check failed: payment-gateway
2024-01-15 10:23:51.001 WARN [kubernetes] HPA - Scaling payment-service from 3 to 5 replicas
2024-01-15 10:24:00.123 ERROR [payment-service] PaymentProcessor - Connection refused to payment gateway: Connection refused (Connection refused)
2024-01-15 10:24:01.234 INFO [oncall] PagerDuty - Alert triggered: PAYMENT_SERVICE_DEGRADED (P1)"""
    
    return {
        "logs": demo_logs,
        "service": "payment-service",
        "severity": "P1",
        "summary": "Payment gateway timeout causing transaction failures"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
