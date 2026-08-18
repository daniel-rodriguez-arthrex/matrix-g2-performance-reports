"""Local web dashboard for the Matrix G2 Performance Test Suite.

A thin Flask orchestration layer over the existing CLI (``run_perf.py``) and the
publish pipeline (``tools/publish_report.py``). The GUI never reimplements test or
publish logic - it shells out to the same scripts teammates would run by hand.
"""
