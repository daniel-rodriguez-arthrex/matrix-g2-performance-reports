import statistics
from typing import Any, Dict, List


class Aggregator:
    def aggregate(self, runs: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not runs:
            return {}
        total_calls = sum(r.get("total_calls", 0) for r in runs)
        total_duration_ms = sum(r.get("total_duration_ms", 0) for r in runs)
        run_totals = [r.get("total_duration_ms", 0) for r in runs]
        avg_d = statistics.mean(run_totals) if run_totals else 0
        max_d = max(run_totals) if run_totals else 0
        min_d = min(run_totals) if run_totals else 0
        p95 = self._percentile(run_totals, 0.95) if run_totals else 0
        return {
            "runs": len(runs),
            "total_calls": total_calls,
            "total_duration_ms": round(total_duration_ms, 2),
            "avg_duration_ms": round(total_duration_ms / total_calls, 2) if total_calls else 0,
            "avg_total_ms": round(avg_d, 2),
            "min_total_ms": round(min_d, 2),
            "max_total_ms": round(max_d, 2),
            "p95_total_ms": round(p95, 2),
            "total_api_calls": total_calls,
            "api_threshold_ms": runs[0].get("api_threshold_ms"),
            "api_pass": all(r.get("api_pass") for r in runs if r.get("api_pass") is not None) if any(r.get("api_pass") is not None for r in runs) else None,
            "errors": [e for r in runs for e in r.get("errors", [])],
            "api_violations": [v for r in runs for v in r.get("api_violations", [])],
            "validation_errors": [e for r in runs for e in r.get("validation_errors", [])],
            "validation_failures": sum(r.get("validation_failures", 0) for r in runs),
            "actions": [a for r in runs for a in r.get("actions", [])],
            "action_count": sum(len(r.get("actions", [])) for r in runs),
        }

    @staticmethod
    def _percentile(data: List[float], percentile: float) -> float:
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * percentile
        f = int(k)
        c = f + 1 if f + 1 < len(sorted_data) else f
        if f == c:
            return sorted_data[f]
        return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)
