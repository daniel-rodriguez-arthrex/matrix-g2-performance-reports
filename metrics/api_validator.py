"""Basic API response validation for Matrix G2.

Validates JSON well-formedness and status codes. This is intentionally a
lightweight starting point; response schemas can be added here later.
"""

import json
from typing import Any, Dict, Optional


class ApiResponseValidator:
    """Validate API responses captured by ApiInterceptor."""

    def validate(
        self,
        status: Optional[int],
        body: Optional[str],
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Return a validation result dict."""
        result = {"is_valid": True, "api_error": None}

        if status is None:
            result["is_valid"] = False
            result["api_error"] = "No response status"
            return result

        if status >= 400:
            result["is_valid"] = False
            result["api_error"] = f"HTTP error {status}"
            return result

        content_type = (headers or {}).get("content-type", "")
        if body and "application/json" in content_type.lower():
            try:
                json.loads(body)
            except json.JSONDecodeError as exc:
                result["is_valid"] = False
                result["api_error"] = f"Invalid JSON: {exc}"

        return result
