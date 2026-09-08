#!/usr/bin/env python3
"""Clean application, wrong-version and reapplication rejection."""
import tempfile
from pathlib import Path
from fetch import ROOT, PIN, extract
from apply import apply

destination = Path(tempfile.mkdtemp(prefix="apply-test-", dir=ROOT / ".scratch"))
extract((ROOT / ".scratch/source.tgz").read_bytes(), destination)
source = destination / f"pi-web-{PIN}"
package = source / "package.json"
original = package.read_bytes()
package.write_bytes(original.replace(b'"0.8.11"', b'"0.9.0"', 1))
try:
    apply(source)
except ValueError as error:
    assert "Unexpected source/version" in str(error)
else:
    raise AssertionError("Wrong version was accepted")
package.write_bytes(original)
apply(source)
try:
    apply(source)
except ValueError as error:
    assert "Unexpected source/version" in str(error)
else:
    raise AssertionError("Patch reapplication was accepted")
print("PASS: clean apply, unexpected source version rejected, repeated apply rejected")
