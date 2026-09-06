#!/usr/bin/env python3
"""Unit tests for Corkboard skill CLI pure logic.

Tests the pure functions from cb_pages.py that can be verified without
a live HTTP server: edit uniqueness, insert anchor resolution, and CAS
retry decision logic.

Usage: python3 tests/test_pages_logic.py
Exit 0 on pass, non-zero on failure.
"""

import os
import sys

# Ensure script/ is on the import path so we can import cb_pages
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "script"))

# ---------------------------------------------------------------------------
# Test framework (stdlib-only, no pytest)
# ---------------------------------------------------------------------------

_failures = 0
_checks = 0


def _check(condition, message):
    global _failures, _checks
    _checks += 1
    if not condition:
        _failures += 1
        print(f"FAIL: {message}")
        # Print a traceback-like line for debugging
        import traceback
        for line in traceback.format_stack()[:-1]:
            pass  # suppress full trace; we print the message
        return False
    return True


def _raises(exc_type, fn, *args, **kwargs):
    """Assert that fn(*args, **kwargs) raises exc_type."""
    try:
        fn(*args, **kwargs)
        _check(False, f"expected {exc_type.__name__} but no exception raised")
        return None
    except exc_type as e:
        return e
    except Exception as e:
        _check(False, f"expected {exc_type.__name__} but got {type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

SAMPLE_BODY = """\
# Introduction

This is the intro section.

## Features

Feature one description.

Feature two description.

### Nested Feature

Nested content here.

## Installation

Run `pip install`.

# License

MIT license text.
"""

# ---------------------------------------------------------------------------
# apply_edits tests
# ---------------------------------------------------------------------------

def test_edit_single_replacement():
    """A single --old/--new pair that matches exactly once succeeds."""
    from cb_pages import apply_edits
    result = apply_edits(SAMPLE_BODY, [("intro section", "overview section")])
    _check("overview section" in result, "replacement text not found")
    _check("intro section" not in result, "original text still present")
    assert "\n" not in ("intro section", "overview section")  # check they're inline


def test_edit_zero_matches_aborts():
    """An --old that matches zero times should raise ValueError."""
    from cb_pages import apply_edits
    err = _raises(ValueError, apply_edits, SAMPLE_BODY, [("nonexistent text", "replacement")])
    _check(err is not None, "zero-match edit did not raise ValueError")
    _check("0 times" in str(err).lower() or "0 matches" in str(err).lower(),
           f"error message should mention zero matches, got: {err}")


def test_edit_multiple_matches_aborts():
    """An --old that matches more than once should raise ValueError."""
    from cb_pages import apply_edits
    # "##" appears multiple times in the body
    err = _raises(ValueError, apply_edits, SAMPLE_BODY, [("##", "##")])
    _check(err is not None, "multi-match edit did not raise ValueError")
    _check("times" in str(err).lower() and "2" not in str(err).lower() or "multiple" in str(err).lower(),
           f"error message should mention multiple matches, got: {err}")


def test_edit_sequential_application():
    """Later edits may anchor on the results of earlier edits."""
    from cb_pages import apply_edits
    body = "first line\nsecond line\nthird line\n"
    # First edit: replace "second line" with "SECOND LINE"
    # Second edit: replace "SECOND LINE" with "line two" (anchors on result of first)
    edits = [
        ("second line", "SECOND LINE"),
        ("SECOND LINE", "line two"),
    ]
    result = apply_edits(body, edits)
    _check("line two" in result, "second edit result not found")
    _check("second line" not in result, "original text still present")
    _check("SECOND LINE" not in result, "intermediate text still present")


def test_edit_sequential_fails_on_second():
    """If the second edit's --old doesn't match (because first edit changed it),
    the entire operation fails — no partial writes."""
    from cb_pages import apply_edits
    body = "first line\nsecond line\nthird line\n"
    edits = [
        ("second line", "SECOND LINE"),
        # This won't match because "second line" was already replaced
        ("second line", "never matches"),
    ]
    err = _raises(ValueError, apply_edits, body, edits)
    _check(err is not None, "sequential edit with bad second edit did not raise")


def test_edit_empty_edits_noop():
    """No edits: return original body unchanged."""
    from cb_pages import apply_edits
    result = apply_edits(SAMPLE_BODY, [])
    _check(result == SAMPLE_BODY, "empty edits should return body unchanged")


def test_edit_edits_file_format():
    """Edits from --edits FILE: one --old/--new pair per line, tab-separated."""
    from cb_pages import parse_edits_file
    import tempfile
    content = "old text\tnew text\nsecond old\tsecond new\n"
    pairs = parse_edits_file(content)
    _check(len(pairs) == 2, f"expected 2 pairs, got {len(pairs)}")
    _check(pairs[0] == ("old text", "new text"), f"first pair wrong: {pairs[0]}")
    _check(pairs[1] == ("second old", "second new"), f"second pair wrong: {pairs[1]}")

    # Empty file
    _check(parse_edits_file("") == [], "empty file should return empty list")

    # Trailing newline
    pairs = parse_edits_file("a\tb\n")
    _check(pairs == [("a", "b")], f"single line with trailing newline: {pairs}")


# ---------------------------------------------------------------------------
# resolve_anchor tests (insert)
# ---------------------------------------------------------------------------

def test_insert_under_heading():
    """Insert content under a heading — after the heading, before next same/higher level."""
    from cb_pages import resolve_anchor
    body = "# Heading 1\n\nContent under H1.\n\n## Subheading\n\nSub content.\n\n# Heading 2\n\nH2 content.\n"
    # Insert under "## Subheading" — should go before "# Heading 2" (same or higher level)
    result = resolve_anchor(body, "## Subheading", "under", "INSERTED\n")
    # Should be after "## Subheading" section and before "# Heading 2"
    _check("INSERTED" in result, "inserted text not found")
    # Verify position: INSERTED appears after Subheading content and before Heading 2
    idx_inserted = result.index("INSERTED")
    idx_sub = result.index("## Subheading")
    idx_h2 = result.index("# Heading 2")
    _check(idx_inserted > idx_sub, "INSERTED should be after Subheading")
    _check(idx_inserted < idx_h2, "INSERTED should be before Heading 2")


def test_insert_under_last_heading():
    """Insert under the last heading — goes to end of document."""
    from cb_pages import resolve_anchor
    body = "# H1\n\nContent.\n\n# H2\n\nLast content.\n"
    result = resolve_anchor(body, "# H2", "under", "APPENDED\n")
    _check(result.endswith("APPENDED\n"), "insert under last heading should go to end of doc")


def test_insert_after_line():
    """Insert after a specific line."""
    from cb_pages import resolve_anchor
    body = "line one\nline two\nline three\n"
    result = resolve_anchor(body, "line two", "after", "INSERTED\n")
    expected = "line one\nline two\nINSERTED\nline three\n"
    _check(result == expected, f"after insert:\n  expected: {repr(expected)}\n  got:      {repr(result)}")


def test_insert_before_line():
    """Insert before a specific line."""
    from cb_pages import resolve_anchor
    body = "line one\nline two\nline three\n"
    result = resolve_anchor(body, "line two", "before", "INSERTED\n")
    expected = "line one\nINSERTED\nline two\nline three\n"
    _check(result == expected, f"before insert:\n  expected: {repr(expected)}\n  got:      {repr(result)}")


def test_insert_anchor_not_found():
    """Anchor that doesn't match any line raises ValueError."""
    from cb_pages import resolve_anchor
    body = "line one\nline two\n"
    err = _raises(ValueError, resolve_anchor, body, "nonexistent", "after", "INSERTED\n")
    _check(err is not None, "missing anchor did not raise ValueError")


def test_insert_anchor_multiple_matches():
    """Anchor that matches multiple lines raises ValueError (exactly-one rule)."""
    from cb_pages import resolve_anchor
    body = "repeat\nunique\nrepeat\n"
    err = _raises(ValueError, resolve_anchor, body, "repeat", "after", "INSERTED\n")
    _check(err is not None, "multi-match anchor did not raise ValueError")


def test_insert_anchor_exact_line_match():
    """Anchor matches the full line, not a substring."""
    from cb_pages import resolve_anchor
    body = "prefix match here\nno match\n"
    # "match" is a substring of line 1, but the anchor is the full line
    err = _raises(ValueError, resolve_anchor, body, "match", "after", "INSERTED\n")
    _check(err is not None, "substring anchor matched — should require exact line match")


def test_insert_under_heading_levels():
    """Under a heading respects heading levels (Markdown ATX)."""
    from cb_pages import resolve_anchor
    body = "## H2\n\nH2 content.\n\n### H3\n\nH3 content.\n\n## H2b\n\nH2b content.\n"
    # Insert under "## H2" — section ends at next ## (same level) or # (higher)
    result = resolve_anchor(body, "## H2", "under", "INSERTED\n")
    idx_inserted = result.index("INSERTED")
    idx_h2b = result.index("## H2b")
    idx_h3 = result.index("### H3")
    _check(idx_inserted > idx_h3, "INSERTED should be after H3 section")
    _check(idx_inserted < idx_h2b, "INSERTED should be before next H2")


def test_insert_unknown_mode():
    """Unknown mode raises ValueError."""
    from cb_pages import resolve_anchor
    err = _raises(ValueError, resolve_anchor, "body", "anchor", "sideways", "INSERTED\n")
    _check(err is not None, "unknown mode did not raise ValueError")


# ---------------------------------------------------------------------------
# should_retry_cas tests
# ---------------------------------------------------------------------------

def test_cas_retry_on_412_first_attempt():
    """On HTTP 412 and first attempt, should retry."""
    from cb_pages import should_retry_cas
    _check(should_retry_cas(412, 1) is True, "first 412 should retry")


def test_cas_retry_on_412_second_attempt():
    """On HTTP 412 and second attempt, should NOT retry."""
    from cb_pages import should_retry_cas
    _check(should_retry_cas(412, 2) is False, "second 412 should not retry")


def test_cas_no_retry_on_other_status():
    """Non-412 status codes should never retry."""
    from cb_pages import should_retry_cas
    for status in (200, 400, 404, 500, 503):
        _check(should_retry_cas(status, 1) is False,
               f"status {status} should not trigger retry")


def test_cas_no_retry_garbage_attempt():
    """Attempt count > 2 should not retry."""
    from cb_pages import should_retry_cas
    _check(should_retry_cas(412, 3) is False, "attempt 3+ should not retry")
    _check(should_retry_cas(412, 0) is False, "attempt 0 should not retry")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Run all test_ functions
    import traceback
    test_funcs = [(name, obj) for name, obj in sorted(globals().items())
                  if name.startswith("test_") and callable(obj)]

    for name, func in test_funcs:
        try:
            func()
        except Exception as e:
            _failures += 1
            print(f"ERROR in {name}: {e}")
            traceback.print_exc()

    print(f"\n{_checks} checks, {_failures} failures")
    if _failures == 0:
        print("ALL TESTS PASSED")
        sys.exit(0)
    else:
        print(f"{_failures} TEST(S) FAILED")
        sys.exit(1)