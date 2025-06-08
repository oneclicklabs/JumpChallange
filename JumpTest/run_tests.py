#!/usr/bin/env python
"""
Run all tests for the Financial Advisor AI agent.
This script runs the core tests and integration tests separately.
"""
from financial_advisor_ai.tests_integrations import run_integration_tests
from financial_advisor_ai.tests import run_tests
import os
import sys
import django

# Add the project directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set up Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "JumpTest.settings")
django.setup()


def main():
    """Run all tests and report results"""
    print("\n" + "="*80)
    print(" FINANCIAL ADVISOR AI - TEST SUITE ".center(80, "="))
    print("="*80 + "\n")

    # Run core tests
    print("\n" + "-"*80)
    print(" CORE TESTS ".center(80, "-"))
    print("-"*80 + "\n")
    core_failures = run_tests()

    # Run integration tests
    print("\n" + "-"*80)
    print(" INTEGRATION TESTS ".center(80, "-"))
    print("-"*80 + "\n")
    integration_failures = run_integration_tests()

    # Report summary
    total_failures = core_failures + integration_failures

    print("\n" + "="*80)
    print(" TEST SUMMARY ".center(80, "="))
    print("="*80)
    print(
        f"Core Tests: {'PASS' if core_failures == 0 else 'FAIL'} ({core_failures} failures)")
    print(
        f"Integration Tests: {'PASS' if integration_failures == 0 else 'FAIL'} ({integration_failures} failures)")
    print("-"*80)
    print(
        f"Overall: {'PASS' if total_failures == 0 else 'FAIL'} ({total_failures} total failures)")
    print("="*80 + "\n")

    return total_failures


if __name__ == "__main__":
    sys.exit(main())
