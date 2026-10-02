"""Run the test suite on GitHub Actions and report each failure as an annotation.

Job logs need a signed-in account to read; annotations are public, so a failed build can be
diagnosed from anywhere without credentials.
"""
import sys
import unittest


def annotate(kind, test, trace):
    lines = trace.strip().splitlines()
    # The last lines carry the assertion or exception; keep the message short enough for an annotation.
    body = '\n'.join(lines[-12:]).replace('%', '%25').replace('\r', '').replace('\n', '%0A')
    print(f'::error title={kind} {test.id()}::{body}', flush=True)


def main():
    suite = unittest.defaultTestLoader.discover('tests')
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    for test, trace in result.failures:
        annotate('FAIL', test, trace)
    for test, trace in result.errors:
        annotate('ERROR', test, trace)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
