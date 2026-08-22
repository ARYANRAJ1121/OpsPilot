"""Offline evaluation harness tests."""

from opspilot.eval_harness import run_eval_suite


def test_eval_suite_passes() -> None:
    report = run_eval_suite()
    assert report["failed"] == 0, report
    assert report["passed"] == report["total"]
    assert report["total"] >= 4
