"""
Unit and integration tests for low-cardinality Prometheus metrics.
Verifies label sanitization, counter and histogram tracking, and Prometheus formatting.
"""
import pytest
from app.core.metrics import MetricsRegistry, classify_endpoint_group, metrics_registry


@pytest.fixture(autouse=True)
def clean_metrics():
    """Ensure a clean metrics registry for each test."""
    metrics_registry.reset()
    yield
    metrics_registry.reset()


def test_metrics_registry_counter_increment():
    """Verifies counter incrementation and standard Prometheus output."""
    registry = MetricsRegistry()
    registry.inc_counter("http_requests_total", 1.0, {"method": "GET", "status": "200"})
    registry.inc_counter("http_requests_total", 2.0, {"method": "GET", "status": "200"})
    registry.inc_counter("http_requests_total", 1.0, {"method": "POST", "status": "201"})

    output = registry.generate_prometheus_output()
    assert '# HELP http_requests_total Total number of HTTP requests processed' in output
    assert '# TYPE http_requests_total counter' in output
    assert 'http_requests_total{method="GET",status="200"} 3.0' in output
    assert 'http_requests_total{method="POST",status="201"} 1.0' in output


def test_metrics_registry_histogram_observation():
    """Verifies histogram bucket calculation, observation count, and sum."""
    registry = MetricsRegistry()
    registry.observe_histogram("http_request_duration_seconds", 0.04, {"handler": "tasks"})
    registry.observe_histogram("http_request_duration_seconds", 0.15, {"handler": "tasks"})

    output = registry.generate_prometheus_output()
    assert '# HELP http_request_duration_seconds Histogram of HTTP request latencies in seconds' in output
    assert '# TYPE http_request_duration_seconds histogram' in output

    # 0.04 is <= 0.05, so bucket 0.05 should be 1
    assert 'http_request_duration_seconds_bucket{handler="tasks",le="0.05"} 1' in output
    # Both 0.04 and 0.15 are <= 0.25, so bucket 0.25 should be 2
    assert 'http_request_duration_seconds_bucket{handler="tasks",le="0.25"} 2' in output
    assert 'http_request_duration_seconds_bucket{handler="tasks",le="+Inf"} 2' in output
    assert 'http_request_duration_seconds_count{handler="tasks"} 2' in output
    assert 'http_request_duration_seconds_sum{handler="tasks"} 0.1900' in output


def test_metrics_strips_forbidden_labels():
    """Ensures high-cardinality and PII labels are stripped."""
    registry = MetricsRegistry()
    forbidden = {
        "user_id": "usr_secret_123",
        "email": "victim@example.com",
        "request_id": "req-999-aaa",
        "task_id": "42",
        "reminder_id": "100",
        "notification_id": "55",
        "message_id": "msg-xyz",
        "token": "bearer_secret",
        "ip": "1.2.3.4",
        "id": "item_9",
        "status": "200",
        "method": "GET",
    }
    registry.inc_counter("http_requests_total", 1.0, forbidden)
    output = registry.generate_prometheus_output()

    assert 'status="200"' in output
    assert 'method="GET"' in output
    assert "user_id" not in output
    assert "usr_secret_123" not in output
    assert "victim@example.com" not in output
    assert "req-999-aaa" not in output
    assert "bearer_secret" not in output
    assert "1.2.3.4" not in output


def test_metrics_strips_user_prefixed_labels():
    """Ensures any user_ prefixed keys are sanitized."""
    registry = MetricsRegistry()
    registry.inc_counter(
        "http_requests_total",
        1.0,
        {"user_name": "alice", "user_org": "corp", "endpoint_group": "tasks"},
    )
    output = registry.generate_prometheus_output()
    assert 'endpoint_group="tasks"' in output
    assert "alice" not in output
    assert "user_name" not in output
    assert "user_org" not in output


def test_metrics_registry_reset():
    """Verifies that reset() clears all counters and histograms."""
    registry = MetricsRegistry()
    registry.inc_counter("http_requests_total", 5.0)
    registry.observe_histogram("http_request_duration_seconds", 0.5)
    assert len(registry._counters) > 0
    assert len(registry._histograms) > 0

    registry.reset()
    assert len(registry._counters) == 0
    assert len(registry._histograms) == 0
    assert registry.generate_prometheus_output().strip() == ""


def test_metrics_prometheus_exposition_format():
    """Verifies standard prometheus text exposition format ends with newline and syntax."""
    registry = MetricsRegistry()
    registry.inc_counter("db_operations_total", 3.0, {"op": "select"})
    output = registry.generate_prometheus_output()
    assert output.endswith("\n")
    assert "# HELP db_operations_total" in output
    assert "# TYPE db_operations_total counter" in output
    assert 'db_operations_total{op="select"} 3.0\n' in output


def test_classify_endpoint_group():
    """Verifies URL paths are mapped to bounded low-cardinality groups."""
    assert classify_endpoint_group("/api/v1/tasks/123") == "tasks"
    assert classify_endpoint_group("/api/v1/reminders") == "reminders"
    assert classify_endpoint_group("/api/v1/notifications/unread") == "notifications"
    assert classify_endpoint_group("/api/v1/gmail/messages/sync") == "gmail"
    assert classify_endpoint_group("/api/v1/calendar/events") == "calendar"
    assert classify_endpoint_group("/api/v1/proactive/summary") == "proactive"
    assert classify_endpoint_group("/api/v1/agent/chat") == "agent"
    assert classify_endpoint_group("/api/v1/knowledge/search") == "knowledge"
    assert classify_endpoint_group("/auth/google/callback") == "auth"
    assert classify_endpoint_group("/health") == "health"
    assert classify_endpoint_group("/ready") == "ready"
    assert classify_endpoint_group("/metrics") == "metrics"
    assert classify_endpoint_group("/unknown/path/here") == "other"


def test_metrics_per_process_semantics():
    """Verifies per-process registry isolation semantics."""
    reg1 = MetricsRegistry()
    reg2 = MetricsRegistry()
    reg1.inc_counter("http_requests_total", 5.0)
    assert reg1._counters.get(("http_requests_total", ())) == 5.0
    assert ("http_requests_total", ()) not in reg2._counters
