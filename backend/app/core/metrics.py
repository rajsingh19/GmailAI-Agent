"""
Low-cardinality Prometheus-compatible metrics registry and collector.
Runs per worker process in-memory.
Never includes high-cardinality or sensitive labels (zero user_id, email, request_id, token, resource_id).
"""
import threading
import time
from typing import Dict, List, Optional, Tuple


class MetricsRegistry:
    """
    Thread-safe in-memory Prometheus metric collector.
    Maintains per-process counters and histograms with strictly bounded label sets.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # Metric key: (name, tuple_of_sorted_labels) -> float value
        self._counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
        # Histogram observations: (name, tuple_of_sorted_labels) -> list of observations
        self._histograms: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], List[float]] = {}
        # Metadata descriptions
        self._descriptions: Dict[str, Tuple[str, str]] = {
            "http_requests_total": (
                "Total number of HTTP requests processed",
                "counter",
            ),
            "http_request_duration_seconds": (
                "Histogram of HTTP request latencies in seconds",
                "histogram",
            ),
            "db_operations_total": (
                "Total number of database operations executed",
                "counter",
            ),
            "llm_requests_total": (
                "Total number of Gemini LLM calls initiated",
                "counter",
            ),
            "llm_request_duration_seconds": (
                "Histogram of Gemini LLM call latencies in seconds",
                "histogram",
            ),
            "google_api_requests_total": (
                "Total number of Google API requests (Gmail, Calendar)",
                "counter",
            ),
            "scheduler_jobs_total": (
                "Total number of scheduler jobs executed",
                "counter",
            ),
            "rate_limit_events_total": (
                "Total number of rate limiting events (allowed or rejected)",
                "counter",
            ),
            "voice_requests_total": (
                "Total number of voice requests processed",
                "counter",
            ),
            "voice_request_duration_seconds": (
                "Histogram of voice request latencies in seconds",
                "histogram",
            ),
            "voice_cancellations_total": (
                "Total number of voice cancellations",
                "counter",
            ),
            "memory_operations_total": (
                "Total number of personal memory operations executed",
                "counter",
            ),
            "personalization_requests_total": (
                "Total number of personalization requests evaluated",
                "counter",
            ),
            "personalization_applied_total": (
                "Total number of personalized context items applied",
                "counter",
            ),
            "personalization_skipped_total": (
                "Total number of personalization requests skipped",
                "counter",
            ),
            "personalization_override_total": (
                "Total number of personalization session/turn overrides triggered",
                "counter",
            ),
            "personalization_latency_seconds": (
                "Histogram of personalization policy latency in seconds",
                "histogram",
            ),
            "personalization_context_chars": (
                "Histogram of personalization context character length",
                "histogram",
            ),
        }

    def _sanitize_labels(self, labels: Optional[Dict[str, str]]) -> Tuple[Tuple[str, str], ...]:
        """Ensures labels do not contain forbidden high-cardinality or PII keys."""
        if not labels:
            return ()
        forbidden_keys = {
            "user_id",
            "email",
            "request_id",
            "task_id",
            "reminder_id",
            "notification_id",
            "message_id",
            "token",
            "id",
            "ip",
        }
        safe_labels = {
            k: str(v)
            for k, v in labels.items()
            if k.lower() not in forbidden_keys and not k.startswith("user_")
        }
        return tuple(sorted(safe_labels.items()))

    def inc_counter(
        self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None
    ) -> None:
        """Increments a counter metric safely."""
        label_tuple = self._sanitize_labels(labels)
        with self._lock:
            key = (name, label_tuple)
            self._counters[key] = self._counters.get(key, 0.0) + value

    def get_sample_value(
        self, name: str, labels: Optional[Dict[str, str]] = None
    ) -> Optional[float]:
        """Retrieves current counter value for testing."""
        label_tuple = self._sanitize_labels(labels)
        with self._lock:
            return self._counters.get((name, label_tuple))

    def observe_histogram(
        self, name: str, value: float, labels: Optional[Dict[str, str]] = None
    ) -> None:
        """Records a histogram observation."""
        label_tuple = self._sanitize_labels(labels)
        with self._lock:
            key = (name, label_tuple)
            if key not in self._histograms:
                self._histograms[key] = []
            self._histograms[key].append(value)
            # Bound histogram observation list length to prevent unbounded memory growth
            if len(self._histograms[key]) > 1000:
                self._histograms[key] = self._histograms[key][-500:]

    def reset(self) -> None:
        """Clears all counters and histograms (for test isolation)."""
        with self._lock:
            self._counters.clear()
            self._histograms.clear()

    def generate_prometheus_output(self) -> str:
        """Generates standard Prometheus exposition text."""
        lines: List[str] = []
        histogram_buckets = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]

        with self._lock:
            # Render counters
            rendered_types = set()
            for (name, label_tuple), val in sorted(self._counters.items()):
                if name not in rendered_types and name in self._descriptions:
                    desc, mtype = self._descriptions[name]
                    lines.append(f"# HELP {name} {desc}")
                    lines.append(f"# TYPE {name} {mtype}")
                    rendered_types.add(name)

                label_str = ""
                if label_tuple:
                    pairs = [f'{k}="{v}"' for k, v in label_tuple]
                    label_str = "{" + ",".join(pairs) + "}"
                lines.append(f"{name}{label_str} {val}")

            # Render histograms
            for (name, label_tuple), observations in sorted(self._histograms.items()):
                if name not in rendered_types and name in self._descriptions:
                    desc, mtype = self._descriptions[name]
                    lines.append(f"# HELP {name} {desc}")
                    lines.append(f"# TYPE {name} {mtype}")
                    rendered_types.add(name)

                count = len(observations)
                total_sum = sum(observations)

                base_label_pairs = [f'{k}="{v}"' for k, v in label_tuple]

                for le in histogram_buckets:
                    bucket_count = sum(1 for o in observations if o <= le)
                    le_label = f'le="{le}"'
                    full_labels = (
                        "{" + ",".join(base_label_pairs + [le_label]) + "}"
                        if base_label_pairs
                        else f"{{{le_label}}}"
                    )
                    lines.append(f"{name}_bucket{full_labels} {bucket_count}")

                inf_labels = (
                    "{" + ",".join(base_label_pairs + ['le="+Inf"']) + "}"
                    if base_label_pairs
                    else '{le="+Inf"}'
                )
                lines.append(f"{name}_bucket{inf_labels} {count}")

                sum_labels = (
                    "{" + ",".join(base_label_pairs) + "}" if base_label_pairs else ""
                )
                lines.append(f"{name}_sum{sum_labels} {total_sum:.4f}")
                lines.append(f"{name}_count{sum_labels} {count}")

        return "\n".join(lines) + "\n"


# Global singleton metrics registry
metrics_registry = MetricsRegistry()


def classify_endpoint_group(path: str) -> str:
    """Classifies URL path into low-cardinality endpoint groups."""
    if path.startswith("/auth"):
        return "auth"
    elif path.startswith("/health"):
        return "health"
    elif path.startswith("/ready"):
        return "ready"
    elif path.startswith("/metrics"):
        return "metrics"
    elif "/tasks" in path:
        return "tasks"
    elif "/reminders" in path:
        return "reminders"
    elif "/notifications" in path:
        return "notifications"
    elif "/gmail" in path:
        return "gmail"
    elif "/calendar" in path:
        return "calendar"
    elif "/proactive" in path:
        return "proactive"
    elif "/agent" in path:
        return "agent"
    elif "/voice" in path:
        return "voice"
    elif "/knowledge" in path:
        return "knowledge"
    elif "/memories" in path:
        return "memories"
    elif "/personalization" in path:
        return "personalization"
    else:
        return "other"
