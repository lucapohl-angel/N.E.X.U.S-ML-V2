"""
Quick Phase 1 Test Script

This script helps you test Phase 1 quickly.
"""

import sys
from pathlib import Path

print("=" * 60)
print("PHASE 1 INITIALIZATION")
print("=" * 60)
print()

# Check if screenshot exists
fixtures_dir = Path("tests/fixtures")
screenshot_path = fixtures_dir / "sample_screenshot.png"

if not screenshot_path.exists():
    print("⚠️  No screenshot found!")
    print()
    print("Please follow these steps:")
    print()
    print("1. Save one of your game screenshots to:")
    print(f"   {screenshot_path.absolute()}")
    print()
    print("2. Then run this command:")
    print("   python tools/phase1_debug_mapping.py tests/fixtures/sample_screenshot.png")
    print()
    print("Tip: Use the 'Overall' tab screenshot (the one showing gold stats)")
    print()
    sys.exit(0)

print("✓ Screenshot found!")
print()
print("Running Phase 1 debug tool...")
print()

# Import and run
sys.path.insert(0, str(Path(__file__).parent))

try:
    from tools.phase1_debug_mapping import main
    main()
except Exception as e:
    print(f"Error: {e}")
    print()
    print("Run manually with:")
    print("python tools/phase1_debug_mapping.py tests/fixtures/sample_screenshot.png")
