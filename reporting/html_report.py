import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
import statistics

# Action types that involve physical hardware motion (camera pan/tilt/zoom, preset recall).
# These are inherently slower than pure software state changes, so they get their own,
# more lenient performance-rating tiers instead of being penalized against software timings.
HARDWARE_ACTION_TYPES = {"camera_move", "camera_preset_call"}

# (excellent_below_ms, acceptable_below_ms, borderline_below_ms) - anything at/above the
# last value is rated "Poor". Based on general UX response-time guidance (Nielsen Norman Group).
SOFTWARE_PERF_TIERS = (500, 1000, 2000)
HARDWARE_PERF_TIERS = (1500, 3000, 5000)


class HtmlReport:
    def generate(self, output_path: Path, data: Dict[str, Any]) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        html = self._render(data)
        output_path.write_text(html, encoding="utf-8")
        return output_path

    def _friendly_timestamp(self, timestamp: str) -> str:
        """Turn '2026-07-22T08:28:43' into 'Jul 22, 2026, 08:28 AM' (falls back to raw input)."""
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(timestamp, fmt).strftime("%b %d, %Y, %I:%M %p")
            except ValueError:
                continue
        return timestamp

    def _render(self, data: Dict[str, Any]) -> str:
        session = data.get("session", {})
        api_calls = data.get("api_calls", [])
        endpoints = data.get("endpoints", [])
        selectors = data.get("selectors", [])
        ws_frames = data.get("ws_frames", [])
        summary = data.get("summary", {})
        actions = summary.get("actions", []) or data.get("actions", [])
        action_stats = self._calculate_action_stats(actions)

        # Filter and aggregate data
        meaningful_calls = self._filter_noise(api_calls)
        grouped_endpoints = self._group_endpoints(meaningful_calls)
        violations = self._find_violations(meaningful_calls, summary.get("api_threshold_ms") or 500)
        app_ws_frames = self._filter_ws_noise(ws_frames)

        # Recompute validation/error/violation counts from meaningful calls so startup
        # noise does not incorrectly fail the report
        filtered_validation_failures = sum(
            1 for c in meaningful_calls if c.get("is_valid") is False
        )
        filtered_errors = [
            c for c in meaningful_calls
            if c.get("error") or (c.get("status") and c.get("status") >= 400)
        ]
        filtered_violations = self._find_violations(meaningful_calls, summary.get("api_threshold_ms") or 500)
        action_errors = action_stats.get("count", 0) - action_stats.get("success_count", 0)
        # Note: SLA (api_threshold_ms) violations and action duration are informational only
        # (see Performance rating) and do not fail the overall report. The report fails only
        # on real API errors or validation failures.
        report_pass = (
            action_stats.get("class") == "status-pass"
            and filtered_validation_failures == 0
            and not filtered_errors
        )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Matrix G2 Performance Report</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 2rem 1rem; }}
        .container {{ max-width: 1400px; margin: 0 auto; background: #ffffff; border-radius: 16px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); overflow: hidden; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: #fff; padding: 2.5rem 2rem; }}
        .header h1 {{ font-size: 2.5rem; font-weight: 700; margin-bottom: 0.5rem; letter-spacing: -0.5px; }}
        .header .meta {{ font-size: 1rem; opacity: 0.9; font-weight: 500; }}
        .content {{ padding: 2rem; }}
        h2 {{ color: #2d3748; font-size: 1.5rem; font-weight: 700; margin: 2.5rem 0 1.5rem 0; padding-bottom: 0.75rem; border-bottom: 3px solid #e2e8f0; }}
        .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1.25rem; margin-bottom: 2.5rem; }}
        .summary-card {{ background: linear-gradient(135deg, #f7fafc 0%, #edf2f7 100%); padding: 1.5rem; border-radius: 12px; border: 1px solid #e2e8f0; transition: transform 0.2s, box-shadow 0.2s; }}
        .summary-card:hover {{ transform: translateY(-2px); box-shadow: 0 8px 16px rgba(0,0,0,0.1); }}
        .summary-card h3 {{ font-size: 0.75rem; color: #718096; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 700; margin-bottom: 0.75rem; }}
        .summary-card .value {{ font-size: 2.25rem; font-weight: 800; line-height: 1; margin-bottom: 0.5rem; }}
        .summary-card .subtext {{ font-size: 0.875rem; color: #718096; }}
        .status-pass {{ color: #38a169; }}
        .status-fail {{ color: #e53e3e; }}
        .status-warn {{ color: #d69e2e; }}
        table {{ width: 100%; border-collapse: separate; border-spacing: 0; background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.08); margin-bottom: 2rem; }}
        th {{ background: linear-gradient(135deg, #4a5568 0%, #2d3748 100%); color: #fff; padding: 1rem; text-align: left; font-size: 0.875rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }}
        td {{ padding: 1rem; font-size: 0.875rem; border-bottom: 1px solid #e2e8f0; word-wrap: break-word; overflow-wrap: break-word; max-width: 320px; }}
        tr:last-child td {{ border-bottom: none; }}
        tr:hover {{ background: #f7fafc; }}
        .metric-good {{ color: #38a169; font-weight: 700; }}
        .metric-warn {{ color: #d69e2e; font-weight: 700; }}
        .metric-bad {{ color: #e53e3e; font-weight: 700; }}
        .badge {{ display: inline-block; padding: 0.375rem 0.75rem; border-radius: 6px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }}
        .badge-success {{ background: #c6f6d5; color: #22543d; }}
        .badge-danger {{ background: #fed7d7; color: #742a2a; }}
        .section-note {{ background: linear-gradient(135deg, #ebf8ff 0%, #e6fffa 100%); padding: 1.25rem; border-radius: 8px; margin-bottom: 1.5rem; border-left: 4px solid #4299e1; font-size: 0.875rem; line-height: 1.6; }}
        .timeline {{ margin: 1.5rem 0; background: #fff; padding: 1.5rem; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
        .timeline-header {{ display: flex; align-items: center; margin-bottom: 1.5rem; padding-bottom: 1rem; border-bottom: 2px solid #e2e8f0; }}
        .timeline-header-label {{ width: 320px; font-size: 0.75rem; font-weight: 700; color: #718096; text-transform: uppercase; letter-spacing: 0.5px; }}
        .timeline-header-scale {{ flex: 1; display: flex; font-size: 0.75rem; color: #a0aec0; font-weight: 600; padding: 0 1rem; position: relative; }}
        .timeline-header-scale span {{ position: absolute; transform: translateX(-50%); }}
        .timeline-header-scale span:nth-child(1) {{ left: 1rem; transform: translateX(0); }}
        .timeline-header-scale span:nth-child(2) {{ left: calc(1rem + 25%); }}
        .timeline-header-scale span:nth-child(3) {{ left: calc(1rem + 50%); }}
        .timeline-header-scale span:nth-child(4) {{ left: calc(1rem + 75%); }}
        .timeline-header-scale span:nth-child(5) {{ left: calc(1rem + 100%); transform: translateX(-100%); }}
        .timeline-row {{ display: flex; align-items: center; margin-bottom: 1rem; padding: 0.5rem 0; border-bottom: 1px solid #f7fafc; }}
        .timeline-row:last-child {{ border-bottom: none; }}
        .timeline-row:hover {{ background: #f7fafc; margin: 0 -1rem 1rem -1rem; padding: 0.5rem 1rem; border-radius: 6px; }}
        .timeline-label {{ width: 320px; font-size: 0.875rem; font-weight: 600; color: #2d3748; padding-right: 1.5rem; line-height: 1.4; }}
        .timeline-track {{ flex: 1; position: relative; height: 40px; display: flex; align-items: center; padding: 0 1rem; }}
        .timeline-bars {{ position: relative; width: 100%; height: 28px; display: flex; }}
        .timeline-bar {{ height: 28px; display: flex; align-items: center; justify-content: center; font-size: 0.7rem; font-weight: 700; color: #fff; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.2s, box-shadow 0.2s; }}
        .timeline-bar:hover {{ transform: translateY(-1px); box-shadow: 0 2px 6px rgba(0,0,0,0.15); }}
        .timeline-bar-text {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 0 6px; }}
        .timeline-times {{ min-width: 200px; font-size: 0.75rem; color: #718096; padding-left: 1.5rem; font-weight: 600; text-align: right; }}
        .bar-api {{ background: linear-gradient(135deg, #4299e1 0%, #2b6cb0 100%); }}
        .bar-ui {{ background: linear-gradient(135deg, #48bb78 0%, #2f855a 100%); }}
        .bar-api-violation {{ background: linear-gradient(135deg, #fc8181 0%, #c53030 100%); }}
        .timeline-legend {{ display: flex; gap: 1.5rem; margin-top: 1rem; padding-top: 1rem; border-top: 1px solid #e2e8f0; font-size: 0.75rem; }}
        .timeline-legend-item {{ display: flex; align-items: center; gap: 0.5rem; }}
        .timeline-legend-box {{ width: 16px; height: 16px; border-radius: 3px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Matrix G2 Performance Report</h1>
            <div class="meta">{session.get("workflow", "N/A").upper()} • Room {session.get("room", "N/A")} • {session.get("timestamp", "")}</div>
        </div>
        <div class="content">
    
    <div class="summary-grid">
        <div class="summary-card">
            <h3>Status</h3>
            <div class="value {'status-pass' if report_pass else 'status-fail'}">
                {'✓ PASS' if report_pass else '✗ FAIL'}
            </div>
            <div class="subtext">{filtered_validation_failures} validation failures, {len(filtered_errors)} errors, {len(filtered_violations)} SLA violations</div>
        </div>
        
        <div class="summary-card">
            <h3>Workflow API Calls</h3>
            <div class="value">{action_stats.get('api_call_count', 0)}</div>
            <div class="subtext">Across {action_stats.get('count', 0)} actions</div>
        </div>
        
        <div class="summary-card">
            <h3>Avg API Time</h3>
            <div class="value {'metric-good' if action_stats.get('p50_api_ms', 0) < 100 else 'metric-warn' if action_stats.get('p50_api_ms', 0) < 500 else 'metric-bad'}">
                {action_stats.get('p50_api_ms', 0):.0f}ms
            </div>
            <div class="subtext">P50 (median) action API time</div>
        </div>
        
        <div class="summary-card">
            <h3>P95 API Time</h3>
            <div class="value {'metric-good' if action_stats.get('p95_api_ms', 0) < (summary.get('api_threshold_ms') or 500) else 'metric-bad'}">
                {action_stats.get('p95_api_ms', 0):.0f}ms
            </div>
            <div class="subtext">Threshold: {summary.get('api_threshold_ms') or 500}ms</div>
        </div>
        
        <div class="summary-card">
            <h3>Slowest Action</h3>
            <div class="value {'metric-good' if action_stats.get('max_api_ms', 0) < (summary.get('api_threshold_ms') or 500) else 'metric-warn' if action_stats.get('max_api_ms', 0) < (summary.get('api_threshold_ms') or 500) * 2 else 'metric-bad'}">
                {action_stats.get('max_api_ms', 0):.0f}ms
            </div>
            <div class="subtext">{action_stats.get('slowest_action_name', '') or 'Max action API time'}</div>
        </div>
        
        <div class="summary-card">
            <h3>Errors</h3>
            <div class="value {'status-pass' if (action_errors + len(filtered_errors)) == 0 else 'status-fail'}">
                {action_errors + len(filtered_errors)}
            </div>
            <div class="subtext">{action_errors} action failures, {len(filtered_errors)} network HTTP errors</div>
        </div>
        
        <div class="summary-card">
            <h3>Actions</h3>
            <div class="value {action_stats.get('class', 'status-pass')}">
                {action_stats.get('success_count', 0)}/{action_stats.get('count', 0)}
            </div>
            <div class="subtext">Actions completed successfully</div>
        </div>
        
        <div class="summary-card">
            <h3>Avg UI Reflection</h3>
            <div class="value {'metric-good' if action_stats.get('avg_ui_ms', 0) < 500 else 'metric-warn' if action_stats.get('avg_ui_ms', 0) < 1000 else 'metric-bad'}">
                {action_stats.get('avg_ui_ms', 0):.0f}ms
            </div>
            <div class="subtext">Time for state to reflect after API call</div>
        </div>
    </div>

    {self._render_network_errors_section(filtered_errors)}
    {self._render_actions_section(actions, summary.get('api_threshold_ms') or 500)}
    {self._render_waterfall_timeline(actions, meaningful_calls)}
    {self._render_violations_section(violations, summary.get('api_threshold_ms') or 500)}
        </div>
    </div>

</body>
</html>"""

    def _filter_noise(self, calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter out thumbnail polling, Socket.IO handshake, and app startup noise."""
        filtered = []
        for call in calls:
            url = call.get("url", "")
            status = call.get("status")
            # Skip thumbnail polling
            if "/thumbnail?ts=" in url:
                continue
            # Skip Socket.IO handshake
            if "EIO=4&transport=" in url:
                continue
            # Skip known app startup noise that fails because the UI requests
            # these before the access token is injected
            if status is not None and status >= 400:
                if (
                    "/api/app/getAccessToken" in url
                    or "/api/app/pair" in url
                    or "/api/system/info" in url
                    or "/api/system/status/rs" in url
                ):
                    continue
            filtered.append(call)
        return filtered
    
    def _group_endpoints(self, calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Group calls by endpoint pattern and calculate stats."""
        groups = defaultdict(list)
        for call in calls:
            url = call.get("url", "")
            # Normalize URL by removing query params and IDs
            pattern = re.sub(r'\?.*$', '', url)  # Remove query string
            pattern = re.sub(r'/[0-9a-f-]{20,}', '/{id}', pattern)  # Replace long IDs
            pattern = re.sub(r'/mna-[0-9-_]+', '/{device}', pattern)  # Replace device IDs
            groups[pattern].append(call)
        
        result = []
        for pattern, group_calls in groups.items():
            durations = [c.get("duration_ms", 0) for c in group_calls]
            statuses = [c.get("status") for c in group_calls]
            errors = [c for c in group_calls if not c.get("is_valid", True)]
            
            result.append({
                "pattern": pattern,
                "count": len(group_calls),
                "avg": statistics.mean(durations) if durations else 0,
                "p50": statistics.median(durations) if durations else 0,
                "p95": statistics.quantiles(durations, n=20)[18] if len(durations) > 1 else (durations[0] if durations else 0),
                "max": max(durations) if durations else 0,
                "errors": len(errors),
                "status_ok": all(200 <= s < 300 for s in statuses if s),
            })
        
        # Sort by P95 descending
        result.sort(key=lambda x: x["p95"], reverse=True)
        return result
    
    def _find_violations(self, calls: List[Dict[str, Any]], threshold: float) -> List[Dict[str, Any]]:
        """Find calls that exceed the SLA threshold."""
        if threshold is None:
            threshold = 500
        return [c for c in calls if isinstance(c.get("duration_ms"), (int, float)) and c.get("duration_ms", 0) > threshold]
    
    def _filter_ws_noise(self, frames: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter out Socket.IO protocol handshake frames."""
        noise_patterns = ["probe", "2", "3", "5", "40", "41"]
        return [f for f in frames if f.get("payload", "").strip() not in noise_patterns]
    
    def _render_violations_section(self, violations: List[Dict[str, Any]], threshold: float) -> str:
        if not violations:
            return ""
        
        rows = []
        for v in violations:
            url = v.get("url", "")
            # Shorten URL for display
            display_url = url.split("?")[0].replace("https://", "").replace("http://", "")
            rows.append(
                f"<tr class='violation'><td>{v.get('method')}</td><td>{display_url}</td>"
                f"<td class='metric-bad'>{v.get('duration_ms', 0):.0f}ms</td>"
                f"<td>{v.get('status')}</td></tr>"
            )
        
        return f"""
    <h2>⚠️ SLA Violations ({len(violations)})</h2>
    <div class="section-note" style="border-left-color: #dc3545; background: #fff5f5;">
        <strong>Warning:</strong> The following API calls exceeded the {threshold}ms threshold.
    </div>
    <table>
        <tr><th>Method</th><th>Endpoint</th><th>Duration</th><th>Status</th></tr>
        {''.join(rows)}
    </table>
        """
    
    def _render_network_errors_section(self, errors: List[Dict[str, Any]]) -> str:
        """Surface the exact failing requests behind the "N errors" summary count, so a
        dev can immediately see which endpoint(s) failed, with what status/error, and how
        often - instead of having to dig through the raw api_calls.csv."""
        if not errors:
            return ""

        grouped: Dict[tuple, Dict[str, Any]] = {}
        for e in errors:
            url = e.get("url", "")
            display_url = url.split("?")[0].replace("https://", "").replace("http://", "")
            message = (e.get("api_error") or e.get("error") or "").splitlines()[0] if (e.get("api_error") or e.get("error")) else ""
            key = (e.get("method"), display_url, e.get("status"), message)
            entry = grouped.setdefault(key, {"count": 0, "durations": []})
            entry["count"] += 1
            if isinstance(e.get("duration_ms"), (int, float)):
                entry["durations"].append(e["duration_ms"])

        rows = []
        for (method, display_url, status, message), info in sorted(grouped.items(), key=lambda kv: -kv[1]["count"]):
            avg_ms = statistics.mean(info["durations"]) if info["durations"] else 0
            rows.append(
                f"<tr><td>{method or '-'}</td><td>{display_url}</td>"
                f"<td class='metric-bad'>{status if status else 'No response'}</td>"
                f"<td>{message or '-'}</td>"
                f"<td>{info['count']}</td>"
                f"<td>{avg_ms:.0f}</td></tr>"
            )

        return f"""
    <h2>🚨 Network Errors ({len(errors)})</h2>
    <div class="section-note" style="border-left-color: #dc3545; background: #fff5f5;">
        <strong>These are the failing requests behind the error count above.</strong> Each row is grouped by
        endpoint/status/message, with how many times it occurred and its average duration.
    </div>
    <table>
        <tr><th>Method</th><th>Endpoint</th><th>Status</th><th>Error</th><th>Count</th><th>Avg Duration (ms)</th></tr>
        {''.join(rows)}
    </table>
        """

    def _render_grouped_endpoint_rows(self, groups: List[Dict[str, Any]], threshold: float) -> str:
        rows = []
        for g in groups:
            pattern = g["pattern"].replace("https://", "").replace("http://", "")
            # Shorten long patterns
            if len(pattern) > 80:
                pattern = pattern[:77] + "..."
            
            p95_class = "metric-good" if g["p95"] < threshold * 0.5 else "metric-warn" if g["p95"] < threshold else "metric-bad"
            status_badge = "badge-success" if g["status_ok"] and g["errors"] == 0 else "badge-danger"
            status_text = "OK" if g["status_ok"] and g["errors"] == 0 else f"{g['errors']} errors"
            
            rows.append(
                f"<tr><td>{pattern}</td><td>{g['count']}</td>"
                f"<td>{g['avg']:.0f}</td><td>{g['p50']:.0f}</td>"
                f"<td class='{p95_class}'>{g['p95']:.0f}</td>"
                f"<td>{g['max']:.0f}</td>"
                f"<td><span class='badge {status_badge}'>{status_text}</span></td></tr>"
            )
        return "\n".join(rows)
    
    def _render_filtered_api_rows(self, calls: List[Dict[str, Any]], threshold: float) -> str:
        rows = []
        for call in calls:
            url = call.get("url", "")
            display_url = url.split("?")[0].replace("https://", "").replace("http://", "")
            if len(display_url) > 100:
                display_url = display_url[:97] + "..."
            
            status = call.get("status")
            status_class = "metric-good" if status and 200 <= status < 300 else "metric-bad"
            duration = call.get("duration_ms", 0)
            duration_class = "metric-good" if duration < threshold * 0.5 else "metric-warn" if duration < threshold else "metric-bad"
            
            notes = []
            if not call.get("is_valid", True):
                notes.append("Validation failed")
            if call.get("api_error"):
                notes.append(call.get("api_error"))
            notes_text = ", ".join(notes) if notes else "-"
            
            row_class = "error-row" if not call.get("is_valid", True) else ""
            
            rows.append(
                f"<tr class='{row_class}'><td>{call.get('method')}</td><td>{display_url}</td>"
                f"<td class='{status_class}'>{status}</td>"
                f"<td class='{duration_class}'>{duration:.0f}</td>"
                f"<td>{notes_text}</td></tr>"
            )
        return "\n".join(rows)

    def _action_passes(self, a: Dict[str, Any]) -> bool:
        """An action fails only on a real API error (exception/non-2xx). Speed is rated
        separately via _performance_rating and never gates pass/fail."""
        return bool(a.get("success"))

    def _performance_rating(self, action_type: str, total_ms: Any) -> "tuple[str, str]":
        """Return (label, css_class) rating total_ms against action-type-aware tiers."""
        if not isinstance(total_ms, (int, float)):
            return ("-", "")
        excellent, acceptable, borderline = (
            HARDWARE_PERF_TIERS if action_type in HARDWARE_ACTION_TYPES else SOFTWARE_PERF_TIERS
        )
        if total_ms < excellent:
            return ("Excellent", "metric-good")
        if total_ms < acceptable:
            return ("Acceptable", "metric-good")
        if total_ms < borderline:
            return ("Borderline", "metric-warn")
        return ("Poor", "metric-bad")

    def _calculate_action_stats(self, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate aggregate statistics for action metrics.

        API timing stats are derived from each action's api_duration_ms (the real
        workflow request/response time), NOT from browser-captured network calls -
        those only see background app-bootstrap/heartbeat traffic in scenario mode.
        """
        count = len(actions)
        if not count:
            return {
                "count": 0, "success_count": 0, "avg_ui_ms": 0, "avg_api_ms": 0,
                "api_call_count": 0, "p50_api_ms": 0, "p95_api_ms": 0, "max_api_ms": 0,
                "slowest_action_name": "", "slowest_action_ms": 0, "class": "status-pass",
            }

        success_count = sum(1 for a in actions if self._action_passes(a))
        ui_ms = [a.get("ui_duration_ms", 0) or 0 for a in actions if a.get("ui_duration_ms") is not None]
        api_ms = [a.get("api_duration_ms", 0) or 0 for a in actions if a.get("api_duration_ms") is not None]
        avg_ui = statistics.mean(ui_ms) if ui_ms else 0
        avg_api = statistics.mean(api_ms) if api_ms else 0

        # Total real workflow API calls (each action records the calls it made).
        api_call_count = sum(len(a.get("api_calls", []) or []) for a in actions)

        p50_api = statistics.median(api_ms) if api_ms else 0
        p95_api = statistics.quantiles(api_ms, n=20)[18] if len(api_ms) > 1 else (api_ms[0] if api_ms else 0)
        max_api = max(api_ms) if api_ms else 0

        # Identify the single slowest action by API time, for an actionable callout.
        slowest = max(
            (a for a in actions if a.get("api_duration_ms") is not None),
            key=lambda a: a.get("api_duration_ms", 0) or 0,
            default=None,
        )

        return {
            "count": count,
            "success_count": success_count,
            "avg_ui_ms": avg_ui,
            "avg_api_ms": avg_api,
            "api_call_count": api_call_count,
            "p50_api_ms": p50_api,
            "p95_api_ms": p95_api,
            "max_api_ms": max_api,
            "slowest_action_name": (slowest.get("name", "") if slowest else ""),
            "slowest_action_ms": (slowest.get("api_duration_ms", 0) or 0 if slowest else 0),
            "class": "status-pass" if success_count == count else "status-fail" if success_count == 0 else "status-warn",
        }

    def _render_actions_section(self, actions: List[Dict[str, Any]], threshold: float) -> str:
        if not actions:
            return ""

        rows = []
        for a in actions:
            passed = self._action_passes(a)
            status_badge = "badge-success" if passed else "badge-danger"
            status_text = "OK" if passed else "ERROR"
            api_ms = a.get("api_duration_ms")
            ui_ms = a.get("ui_duration_ms")
            total_ms = a.get("total_duration_ms")
            action_type = a.get("action_type", "")

            api_text = f"{api_ms:.0f}" if isinstance(api_ms, (int, float)) else "-"
            ui_text = f"{ui_ms:.0f}" if isinstance(ui_ms, (int, float)) else "-"
            total_text = f"{total_ms:.0f}" if isinstance(total_ms, (int, float)) else "-"

            api_class = "metric-good" if api_ms and api_ms < threshold * 0.5 else "metric-warn" if api_ms and api_ms < threshold else "metric-bad"
            ui_class = "metric-good" if ui_ms and ui_ms < 500 else "metric-warn" if ui_ms and ui_ms < 1000 else "metric-bad"
            perf_label, perf_class = self._performance_rating(action_type, total_ms)

            error = a.get("error") or ""
            details = a.get("details", {})
            details_text = "<br>".join(f"{k}: {v}" for k, v in details.items())
            endpoints_text = "<br>".join(a.get("api_calls", []) or []) or "-"

            rows.append(
                f"<tr><td>{a.get('name', '')}</td><td>{action_type}</td>"
                f"<td>{endpoints_text}</td>"
                f"<td class='{api_class}'>{api_text}</td>"
                f"<td class='{ui_class}'>{ui_text}</td>"
                f"<td class='{perf_class}'>{total_text}</td>"
                f"<td class='{perf_class}'>{perf_label}</td>"
                f"<td><span class='badge {status_badge}'>{status_text}</span></td>"
                f"<td>{details_text}</td><td>{error}</td></tr>"
            )

        passed_count = sum(1 for a in actions if self._action_passes(a))
        return f"""
    <h2>Actions ({passed_count}/{len(actions)} successful)</h2>
    <div class="section-note">
        <strong>Action-level metrics:</strong> API time is the request/response duration. UI reflection time is how long it took for the backend state (polled via API) to show the change. Status reflects real API errors only. Performance rates total duration against action-type-aware response-time tiers (hardware actions like camera zoom/preset recall get more lenient tiers than pure software actions). Endpoint(s) shows the exact API call(s) this action made, to speed up root-causing failures.
    </div>
    <table>
        <tr><th>Action</th><th>Type</th><th>Endpoint(s)</th><th>API (ms)</th><th>UI Reflection (ms)</th><th>Total (ms)</th><th>Performance</th><th>Status</th><th>Details</th><th>Error</th></tr>
        {''.join(rows)}
    </table>
        """

    def _render_waterfall_timeline(self, actions: List[Dict[str, Any]], calls: List[Dict[str, Any]]) -> str:
        if not actions:
            return ""

        # Use a fixed scale for better readability
        # Find the max total duration to set scale, but cap outliers
        durations = [a.get("total_duration_ms", 0) for a in actions]
        max_duration = max(durations) if durations else 1000
        
        # Use a reasonable scale: if max is under 1s, scale to 1s; if under 3s, scale to max; else use log-like bucketing
        if max_duration <= 1000:
            scale_max = 1000
        elif max_duration <= 3000:
            scale_max = max_duration
        else:
            # For very long actions, use a compressed scale
            scale_max = 3000
        
        rows = []
        for a in actions:
            api_ms = a.get("api_duration_ms") or 0
            ui_ms = a.get("ui_duration_ms") or 0
            total_ms = a.get("total_duration_ms") or 0
            
            # Calculate widths as percentage of scale_max
            # Cap at 100% for outliers
            api_pct = min((api_ms / scale_max) * 100, 100)
            ui_pct = min((ui_ms / scale_max) * 100, 100 - api_pct)
            total_pct = min((total_ms / scale_max) * 100, 100)
            
            # Ensure bars are visible even for very fast actions (min 2%)
            if api_ms > 0 and api_pct < 2:
                api_pct = 2
            if ui_ms > 0 and ui_pct < 2:
                ui_pct = 2
            
            bar_color = "bar-api" if a.get("success") else "bar-api-violation"
            label = a.get("name", a.get("action_type", "Action"))
            
            # Show time in bar if there's space
            api_text = f"{api_ms:.0f}ms" if api_pct > 8 else ""
            ui_text = f"{ui_ms:.0f}ms" if ui_pct > 8 else ""

            rows.append(
                f"""<div class="timeline-row">
                    <div class="timeline-label" title="{label}">{label}</div>
                    <div class="timeline-track">
                        <div class="timeline-bars">
                            <div class="timeline-bar {bar_color}" style="width: {api_pct:.1f}%;" title="API: {api_ms:.0f}ms">
                                <span class="timeline-bar-text">{api_text}</span>
                            </div>
                            <div class="timeline-bar bar-ui" style="width: {ui_pct:.1f}%;" title="UI reflection: {ui_ms:.0f}ms">
                                <span class="timeline-bar-text">{ui_text}</span>
                            </div>
                        </div>
                    </div>
                    <div class="timeline-times">{total_ms:.0f}ms<br><span style="font-size: 0.65rem; color: #a0aec0;">{api_ms:.0f} + {ui_ms:.0f}</span></div>
                </div>"""
            )
        
        # Create scale markers
        scale_markers = []
        step = scale_max // 4
        for i in range(5):
            ms = i * step
            scale_markers.append(f"<span>{ms}ms</span>")

        return f"""
    <h2>Action Timeline</h2>
    <div class="section-note">
        <strong>Performance breakdown:</strong> Each bar shows API request time (blue) + UI reflection time (green). Scale: 0-{scale_max}ms.
    </div>
    <div class="timeline">
        <div class="timeline-header">
            <div class="timeline-header-label">Action</div>
            <div class="timeline-header-scale">
                {''.join(scale_markers)}
            </div>
            <div class="timeline-times" style="text-align: right; padding-left: 1.5rem;">Total</div>
        </div>
        {''.join(rows)}
        <div class="timeline-legend">
            <div class="timeline-legend-item">
                <div class="timeline-legend-box" style="background: linear-gradient(135deg, #4299e1 0%, #2b6cb0 100%);"></div>
                <span>API Request</span>
            </div>
            <div class="timeline-legend-item">
                <div class="timeline-legend-box" style="background: linear-gradient(135deg, #48bb78 0%, #2f855a 100%);"></div>
                <span>UI Reflection (polling)</span>
            </div>
            <div class="timeline-legend-item">
                <div class="timeline-legend-box" style="background: linear-gradient(135deg, #fc8181 0%, #c53030 100%);"></div>
                <span>Failed Action</span>
            </div>
        </div>
    </div>
        """

    def _render_selector_section(self, selectors: List[Dict[str, Any]]) -> str:
        if not selectors:
            return ""
        
        rows = []
        for s in selectors:
            found_class = "metric-good" if s.get("found") else "metric-bad"
            visible_class = "metric-good" if s.get("visible") else "metric-warn"
            rows.append(
                f"<tr><td>{s.get('selector')}</td><td>{s.get('strategy')}</td>"
                f"<td class='{found_class}'>{s.get('found')}</td>"
                f"<td class='{visible_class}'>{s.get('visible')}</td>"
                f"<td>{s.get('count')}</td><td>{s.get('suggested', '-')}</td></tr>"
            )
        
        return f"""
    <h2>UI Selector Validation</h2>
    <table>
        <tr><th>Selector</th><th>Strategy</th><th>Found</th><th>Visible</th><th>Count</th><th>Suggested</th></tr>
        {''.join(rows)}
    </table>
        """

    def _render_selector_rows(self, selectors: List[Dict[str, Any]]) -> str:
        rows = []
        for s in selectors:
            found_class = "ok" if s.get("found") else "fail"
            visible_class = "ok" if s.get("visible") else "fail"
            rows.append(
                f"<tr><td>{s.get('selector')}</td><td>{s.get('strategy')}</td>"
                f"<td class='{found_class}'>{s.get('found')}</td>"
                f"<td class='{visible_class}'>{s.get('visible')}</td>"
                f"<td>{s.get('count')}</td><td>{s.get('suggested', '')}</td></tr>"
            )
        return "\n".join(rows)

    def _render_websocket_section(self, frames: List[Dict[str, Any]]) -> str:
        if not frames:
            return ""
        
        rows = []
        for f in frames:
            payload = (f.get("payload") or "").replace("<", "&lt;").replace(">", "&gt;")
            url = f.get("url", "").split("?")[0]
            rows.append(
                f"<tr><td>{f.get('direction')}</td><td>{url}</td>"
                f"<td><pre>{payload[:200]}</pre></td></tr>"
            )
        
        return f"""
    <h2>WebSocket Messages ({len(frames)})</h2>
    <div class="section-note">
        <strong>Note:</strong> Socket.IO handshake frames filtered. Showing application-level messages only.
    </div>
    <table>
        <tr><th>Direction</th><th>URL</th><th>Payload (truncated)</th></tr>
        {''.join(rows)}
    </table>
        """
