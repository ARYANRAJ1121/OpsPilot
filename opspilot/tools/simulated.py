"""
opspilot/tools/simulated.py

Simulated tool registry for development and testing.

Every tool registered in the Policy Engine's TOOL_TIER_REGISTRY has a
matching implementation here that returns deterministic fake data.  No
external calls are made — agents can run fully offline during development.

Public API:
    execute_tool(tool_name, parameters) -> ToolOutput
    SIMULATED_TOOLS                     -> dict of all registered callables
"""

from typing import Any

import structlog

from opspilot.schemas import ToolOutput

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Type alias for a tool implementation
# ---------------------------------------------------------------------------

ToolFn = "Callable[[dict[str, Any]], dict[str, Any]]"

# ---------------------------------------------------------------------------
# Tier 1 — read-only implementations
# ---------------------------------------------------------------------------


def _fetch_logs(params: dict[str, Any]) -> dict[str, Any]:
    service = params.get("service", "unknown-service")
    return {
        "service": service,
        "lines": [
            f"[ERROR] {service}: connection timeout after 30s",
            f"[WARN]  {service}: retry attempt 3/3",
            f"[ERROR] {service}: upstream responded with 503",
        ],
        "total_errors_last_5m": 47,
    }


def _read_metrics(params: dict[str, Any]) -> dict[str, Any]:
    service = params.get("service", "unknown-service")
    return {
        "service": service,
        "error_rate_pct": 18.3,
        "p99_latency_ms": 4200,
        "p50_latency_ms": 310,
        "requests_per_sec": 142,
        "cpu_pct": 88.1,
        "memory_pct": 74.5,
    }


def _describe_service(params: dict[str, Any]) -> dict[str, Any]:
    service = params.get("service", "unknown-service")
    return {
        "service": service,
        "version": "v2.14.1",
        "replicas": {"desired": 3, "ready": 2, "unavailable": 1},
        "last_deploy": "2026-08-17T09:12:00Z",
        "health": "degraded",
    }


def _list_pods(params: dict[str, Any]) -> dict[str, Any]:
    namespace = params.get("namespace", "default")
    return {
        "namespace": namespace,
        "pods": [
            {"name": "api-6d9f4-xk2pq", "status": "Running",  "restarts": 0},
            {"name": "api-6d9f4-r7tnv", "status": "CrashLoopBackOff", "restarts": 8},
            {"name": "api-6d9f4-m2wlh", "status": "Running",  "restarts": 1},
        ],
    }


def _get_config(params: dict[str, Any]) -> dict[str, Any]:
    key = params.get("key", "")
    return {
        "key": key,
        "value": "simulated-config-value",
        "source": "ConfigMap/app-config",
        "last_modified": "2026-08-10T14:00:00Z",
    }


def _search_runbook(params: dict[str, Any]) -> dict[str, Any]:
    query = params.get("query", "")
    return {
        "query": query,
        "results": [
            {
                "title": "Service Recovery Runbook",
                "url": "https://wiki.internal/runbooks/service-recovery",
                "relevance": 0.91,
                "steps": [
                    "Check pod restart count",
                    "Inspect logs for OOM or connection errors",
                    "Restart affected pods if restarts < 10",
                    "Escalate to on-call if issue persists > 15 min",
                ],
            }
        ],
    }


def _get_deployment_status(params: dict[str, Any]) -> dict[str, Any]:
    service = params.get("service", "unknown-service")
    return {
        "service": service,
        "rollout_status": "degraded",
        "current_image": "registry/api:v2.14.1",
        "previous_image": "registry/api:v2.14.0",
        "progress_deadline_exceeded": False,
    }


def _query_apm(params: dict[str, Any]) -> dict[str, Any]:
    service = params.get("service", "unknown-service")
    return {
        "service": service,
        "top_errors": [
            {"error": "ConnectionResetError", "count": 312, "first_seen": "18m ago"},
            {"error": "TimeoutError",          "count": 89,  "first_seen": "21m ago"},
        ],
        "traces_sampled": 1000,
        "error_traces_pct": 22.4,
    }


# ---------------------------------------------------------------------------
# Tier 2 — reversible write implementations
# ---------------------------------------------------------------------------


def _restart_service(params: dict[str, Any]) -> dict[str, Any]:
    service = params.get("service", "unknown-service")
    target = params.get("target", "all-pods")
    return {
        "service": service,
        "target": target,
        "restarted_pods": ["api-6d9f4-r7tnv"],
        "status": "restart_initiated",
        "estimated_recovery_sec": 30,
    }


def _toggle_feature_flag(params: dict[str, Any]) -> dict[str, Any]:
    flag = params.get("flag", "")
    enabled = params.get("enabled", False)
    return {
        "flag": flag,
        "previous_value": not enabled,
        "new_value": enabled,
        "status": "updated",
    }


def _flush_cache(params: dict[str, Any]) -> dict[str, Any]:
    cache = params.get("cache", "default")
    return {
        "cache": cache,
        "keys_flushed": 8421,
        "status": "flushed",
    }


def _scale_deployment(params: dict[str, Any]) -> dict[str, Any]:
    service = params.get("service", "unknown-service")
    replicas = params.get("replicas", 3)
    return {
        "service": service,
        "previous_replicas": 2,
        "new_replicas": replicas,
        "status": "scaling_initiated",
    }


def _rollback_deployment(params: dict[str, Any]) -> dict[str, Any]:
    service = params.get("service", "unknown-service")
    return {
        "service": service,
        "rolled_back_to": "registry/api:v2.14.0",
        "from_version":   "registry/api:v2.14.1",
        "status": "rollback_initiated",
        "estimated_completion_sec": 60,
    }


def _disable_endpoint(params: dict[str, Any]) -> dict[str, Any]:
    endpoint = params.get("endpoint", "")
    return {
        "endpoint": endpoint,
        "status": "disabled",
        "traffic_redirected_to": params.get("fallback", "maintenance-page"),
    }


def _throttle_traffic(params: dict[str, Any]) -> dict[str, Any]:
    service = params.get("service", "unknown-service")
    rate_pct = params.get("rate_pct", 50)
    return {
        "service": service,
        "throttle_rate_pct": rate_pct,
        "status": "throttling_active",
    }


# ---------------------------------------------------------------------------
# Tier 3 — high-risk write implementations
# ---------------------------------------------------------------------------


def _run_db_migration(params: dict[str, Any]) -> dict[str, Any]:
    migration = params.get("migration_id", "")
    return {
        "migration_id": migration,
        "status": "simulated_complete",
        "rows_affected": 50000,
        "duration_sec": 12,
        "warning": "SIMULATED — no real DB touched",
    }


def _delete_resource(params: dict[str, Any]) -> dict[str, Any]:
    resource = params.get("resource", "")
    return {
        "resource": resource,
        "status": "simulated_deleted",
        "warning": "SIMULATED — no real resource deleted",
    }


def _rotate_secret(params: dict[str, Any]) -> dict[str, Any]:
    secret = params.get("secret_name", "")
    return {
        "secret_name": secret,
        "new_version": "v2",
        "status": "simulated_rotated",
        "warning": "SIMULATED — no real secret rotated",
    }


def _teardown_infra(params: dict[str, Any]) -> dict[str, Any]:
    stack = params.get("stack", "")
    return {
        "stack": stack,
        "status": "simulated_teardown",
        "warning": "SIMULATED — no real infra destroyed",
    }


def _modify_iam_policy(params: dict[str, Any]) -> dict[str, Any]:
    policy = params.get("policy_name", "")
    return {
        "policy_name": policy,
        "status": "simulated_modified",
        "warning": "SIMULATED — no real IAM policy changed",
    }


def _wipe_queue(params: dict[str, Any]) -> dict[str, Any]:
    queue = params.get("queue", "")
    return {
        "queue": queue,
        "messages_wiped": 1203,
        "status": "simulated_wiped",
        "warning": "SIMULATED — no real queue wiped",
    }


def _force_failover(params: dict[str, Any]) -> dict[str, Any]:
    service = params.get("service", "unknown-service")
    return {
        "service": service,
        "failed_over_to": params.get("target_region", "us-east-1"),
        "status": "simulated_failover",
        "warning": "SIMULATED — no real failover triggered",
    }


# ---------------------------------------------------------------------------
# Registry — keys must match TOOL_TIER_REGISTRY in policy_engine.py
# ---------------------------------------------------------------------------

SIMULATED_TOOLS: dict[str, Any] = {
    # Tier 1
    "fetch_logs":            _fetch_logs,
    "read_metrics":          _read_metrics,
    "describe_service":      _describe_service,
    "list_pods":             _list_pods,
    "get_config":            _get_config,
    "search_runbook":        _search_runbook,
    "get_deployment_status": _get_deployment_status,
    "query_apm":             _query_apm,
    # Tier 2
    "restart_service":       _restart_service,
    "toggle_feature_flag":   _toggle_feature_flag,
    "flush_cache":           _flush_cache,
    "scale_deployment":      _scale_deployment,
    "rollback_deployment":   _rollback_deployment,
    "disable_endpoint":      _disable_endpoint,
    "throttle_traffic":      _throttle_traffic,
    # Tier 3
    "run_db_migration":      _run_db_migration,
    "delete_resource":       _delete_resource,
    "rotate_secret":         _rotate_secret,
    "teardown_infra":        _teardown_infra,
    "modify_iam_policy":     _modify_iam_policy,
    "wipe_queue":            _wipe_queue,
    "force_failover":        _force_failover,
}


def execute_tool(tool_name: str, parameters: dict[str, Any]) -> ToolOutput:
    """
    Backward-compatible entrypoint — delegates to ``tools.executor``.
    """
    from opspilot.tools.executor import execute_tool as _execute

    return _execute(tool_name, parameters)
