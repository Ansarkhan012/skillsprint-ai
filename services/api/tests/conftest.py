import os
import sys
from pathlib import Path

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-public-key")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Compact-generation caps come from .env at request time; tests default to uncapped.
for _name in ("GENERATION_MAX_OBJECTIVES_PER_MODULE", "GENERATION_MAX_TASKS_PER_MODULE",
              "GENERATION_MAX_CHECKLIST_PER_MODULE", "GENERATION_MAX_QUIZ_PER_MODULE",
              "GENERATION_MAX_TEXT_LENGTH"):
    os.environ[_name] = ""
