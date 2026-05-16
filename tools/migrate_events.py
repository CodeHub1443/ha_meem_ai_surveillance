"""Migrate existing events.jsonl (and rotated backups) into events.db.

Run once from the project root:
    python tools/migrate_events.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database.event_store import EventStore

store = EventStore()
existing = store.count()
if existing:
    print(f"DB already has {existing} events — skipping rows that already exist.")

jsonl_files = sorted(Path("logs").glob("events*.jsonl"), reverse=True)
if not jsonl_files:
    print("No events.jsonl files found in logs/. Nothing to migrate.")
    sys.exit(0)

total = 0
for path in jsonl_files:
    count = 0
    errors = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                store.insert(event)
                count += 1
            except Exception as e:
                errors += 1
                if errors <= 5:
                    print(f"  skip bad line in {path.name}: {e}")
    print(f"  {path.name}: {count} events migrated" + (f", {errors} skipped" if errors else ""))
    total += count

print(f"\nDone. Migrated {total} events. DB now has {store.count()} total events.")
