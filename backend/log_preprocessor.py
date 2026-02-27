"""
Log Preprocessor - Intelligent Log Deduplication and Pattern Extraction

Reduces log noise by grouping similar errors, removing duplicates,
and extracting representative samples for LLM analysis.
"""

import re
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARN = "WARN"
    INFO = "INFO"
    DEBUG = "DEBUG"


@dataclass
class ErrorPattern:
    """Represents a grouped error pattern"""
    error_signature: str
    error_type: str
    count: int
    first_seen: str
    last_seen: str
    severity: str
    affected_service: Optional[str]
    sample_logs: List[Dict[str, Any]]
    trace_ids: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_signature": self.error_signature,
            "error_type": self.error_type,
            "count": self.count,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "severity": self.severity,
            "affected_service": self.affected_service,
            "sample_logs": self.sample_logs[:3],  # Only first 3 samples
            "trace_ids": self.trace_ids[:5]  # Only first 5 trace IDs
        }


@dataclass
class PreprocessingResult:
    """Result of log preprocessing"""
    error_patterns: List[ErrorPattern]
    original_count: int
    deduplicated_count: int
    reduction_percentage: float
    time_range: Dict[str, str]
    severity_distribution: Dict[str, int]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_patterns": [p.to_dict() for p in self.error_patterns],
            "original_count": self.original_count,
            "deduplicated_count": self.deduplicated_count,
            "reduction_percentage": self.reduction_percentage,
            "time_range": self.time_range,
            "severity_distribution": self.severity_distribution
        }


class LogPreprocessor:
    """Intelligent log preprocessor for noise reduction"""
    
    # Common error patterns to extract
    ERROR_PATTERNS = [
        r'(Exception|Error):\s*(.+?)(?:\n|$)',
        r'(\w+Exception)',
        r'(timeout|timed out)',
        r'(connection refused|connection failed)',
        r'(404|500|502|503)',
        r'(out of memory|OOM)',
        r'(null pointer|NullPointerException)',
        r'(deadlock|race condition)',
    ]
    
    def __init__(self, severity_filter: List[str] = None):
        """
        Initialize preprocessor
        
        Args:
            severity_filter: Only include these severity levels (default: ERROR, WARN, CRITICAL)
        """
        self.severity_filter = severity_filter or ["ERROR", "WARN", "CRITICAL"]
    
    def preprocess(
        self,
        logs: List[Dict[str, Any]],
        time_window: Optional[Dict[str, str]] = None
    ) -> PreprocessingResult:
        """
        Preprocess logs with deduplication and pattern extraction
        
        Args:
            logs: List of log entries (dicts with timestamp, level, message, service, etc.)
            time_window: Optional dict with 'start' and 'end' ISO timestamps
            
        Returns:
            PreprocessingResult with deduplicated patterns and statistics
        """
        original_count = len(logs)
        
        # Step 1: Filter by time window and severity
        filtered_logs = self._filter_logs(logs, time_window)
        
        # Step 2: Extract error patterns and group similar logs
        error_patterns = self._extract_patterns(filtered_logs)
        
        # Step 3: Calculate statistics
        deduplicated_count = len(error_patterns)
        reduction_percentage = (
            ((original_count - deduplicated_count) / original_count * 100)
            if original_count > 0 else 0.0
        )
        
        time_range = self._get_time_range(filtered_logs)
        severity_dist = self._get_severity_distribution(filtered_logs)
        
        return PreprocessingResult(
            error_patterns=error_patterns,
            original_count=original_count,
            deduplicated_count=deduplicated_count,
            reduction_percentage=round(reduction_percentage, 2),
            time_range=time_range,
            severity_distribution=severity_dist
        )
    
    def _filter_logs(
        self,
        logs: List[Dict[str, Any]],
        time_window: Optional[Dict[str, str]] = None
    ) -> List[Dict[str, Any]]:
        """Filter logs by severity and time window"""
        filtered = []
        
        for log in logs:
            # Filter by severity
            level = log.get("level", "INFO").upper()
            if level not in self.severity_filter:
                continue
            
            # Filter by time window if provided
            if time_window:
                timestamp = log.get("timestamp", "")
                if not self._is_in_time_window(timestamp, time_window):
                    continue
            
            filtered.append(log)
        
        return filtered
    
    def _is_in_time_window(
        self,
        timestamp: str,
        time_window: Dict[str, str]
    ) -> bool:
        """Check if timestamp is within time window"""
        try:
            ts = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            start = datetime.fromisoformat(time_window['start'].replace('Z', '+00:00'))
            end = datetime.fromisoformat(time_window['end'].replace('Z', '+00:00'))
            return start <= ts <= end
        except:
            return True  # Include if parsing fails
    
    def _extract_patterns(self, logs: List[Dict[str, Any]]) -> List[ErrorPattern]:
        """Group similar errors and extract patterns"""
        pattern_groups = defaultdict(list)
        
        for log in logs:
            signature = self._generate_signature(log)
            pattern_groups[signature].append(log)
        
        # Convert groups to ErrorPattern objects
        patterns = []
        for signature, group_logs in pattern_groups.items():
            pattern = self._create_error_pattern(signature, group_logs)
            patterns.append(pattern)
        
        # Sort by count (most frequent first)
        patterns.sort(key=lambda p: p.count, reverse=True)
        
        return patterns
    
    def _generate_signature(self, log: Dict[str, Any]) -> str:
        """Generate a signature for grouping similar logs"""
        message = log.get("message", "")
        
        # Extract error type
        error_type = "Unknown"
        for pattern in self.ERROR_PATTERNS:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                error_type = match.group(1) if match.groups() else match.group(0)
                break
        
        # Normalize message (remove numbers, IDs, timestamps)
        normalized = re.sub(r'\d+', 'N', message)
        normalized = re.sub(r'[a-f0-9]{8,}', 'ID', normalized)
        normalized = re.sub(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', 'TIMESTAMP', normalized)
        
        # Create signature from service + error type + normalized message
        service = log.get("service", "unknown")
        level = log.get("level", "INFO")
        
        signature_str = f"{service}:{level}:{error_type}:{normalized[:100]}"
        
        # Hash to create shorter signature
        signature_hash = hashlib.md5(signature_str.encode()).hexdigest()[:12]
        
        return f"{error_type}:{signature_hash}"
    
    def _create_error_pattern(
        self,
        signature: str,
        logs: List[Dict[str, Any]]
    ) -> ErrorPattern:
        """Create an ErrorPattern from grouped logs"""
        error_type = signature.split(':')[0]
        
        # Sort by timestamp
        sorted_logs = sorted(logs, key=lambda x: x.get("timestamp", ""))
        
        first_log = sorted_logs[0]
        last_log = sorted_logs[-1]
        
        # Extract trace IDs
        trace_ids = [
            log.get("trace_id", "")
            for log in sorted_logs
            if log.get("trace_id")
        ]
        
        return ErrorPattern(
            error_signature=signature,
            error_type=error_type,
            count=len(logs),
            first_seen=first_log.get("timestamp", ""),
            last_seen=last_log.get("timestamp", ""),
            severity=first_log.get("level", "ERROR"),
            affected_service=first_log.get("service"),
            sample_logs=sorted_logs[:3],  # Keep first 3 as samples
            trace_ids=trace_ids
        )
    
    def _get_time_range(self, logs: List[Dict[str, Any]]) -> Dict[str, str]:
        """Get time range of logs"""
        if not logs:
            return {"start": "", "end": ""}
        
        timestamps = [log.get("timestamp", "") for log in logs if log.get("timestamp")]
        if not timestamps:
            return {"start": "", "end": ""}
        
        return {
            "start": min(timestamps),
            "end": max(timestamps)
        }
    
    def _get_severity_distribution(self, logs: List[Dict[str, Any]]) -> Dict[str, int]:
        """Get distribution of severity levels"""
        distribution = defaultdict(int)
        for log in logs:
            level = log.get("level", "INFO").upper()
            distribution[level] += 1
        return dict(distribution)
    
    def format_for_llm(self, result: PreprocessingResult) -> str:
        """
        Format preprocessing result for LLM consumption
        
        Returns a concise, structured text representation optimized for LLM analysis
        """
        output = []
        
        output.append("=== LOG ANALYSIS SUMMARY ===\n")
        output.append(f"Total Log Lines: {result.original_count}")
        output.append(f"Unique Error Patterns: {result.deduplicated_count}")
        output.append(f"Noise Reduction: {result.reduction_percentage}%")
        output.append(f"Time Range: {result.time_range['start']} to {result.time_range['end']}\n")
        
        output.append("=== SEVERITY DISTRIBUTION ===")
        for severity, count in sorted(result.severity_distribution.items()):
            output.append(f"{severity}: {count}")
        
        output.append("\n=== ERROR PATTERNS (Top 10) ===\n")
        
        for i, pattern in enumerate(result.error_patterns[:10], 1):
            output.append(f"--- Pattern #{i}: {pattern.error_type} ---")
            output.append(f"Occurrences: {pattern.count}")
            output.append(f"First Seen: {pattern.first_seen}")
            output.append(f"Last Seen: {pattern.last_seen}")
            output.append(f"Severity: {pattern.severity}")
            if pattern.affected_service:
                output.append(f"Service: {pattern.affected_service}")
            
            # Add sample log
            if pattern.sample_logs:
                sample = pattern.sample_logs[0]
                output.append(f"Sample Message: {sample.get('message', '')[:200]}")
            
            output.append("")  # Blank line between patterns
        
        return "\n".join(output)


def parse_raw_logs(raw_log_text: str) -> List[Dict[str, Any]]:
    """
    Parse raw log text into structured format
    
    Handles common log formats and converts to dict format for preprocessing
    """
    logs = []
    lines = raw_log_text.strip().split('\n')
    
    for line in lines:
        if not line.strip():
            continue
        
        log_entry = _parse_log_line(line)
        if log_entry:
            logs.append(log_entry)
    
    return logs


def _parse_log_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse a single log line into a dictionary"""
    # Try JSON format first
    if line.strip().startswith('{'):
        try:
            import json
            return json.loads(line)
        except:
            pass
    
    # Try common log format: timestamp level service message
    pattern = r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[Z\+\-\d:]*)\s+(\w+)\s+(\S+)\s+(.+)'
    match = re.match(pattern, line)
    
    if match:
        return {
            "timestamp": match.group(1),
            "level": match.group(2),
            "service": match.group(3),
            "message": match.group(4)
        }
    
    # Fallback: treat entire line as message
    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "level": "INFO",
        "service": "unknown",
        "message": line
    }
