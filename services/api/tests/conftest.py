import os
import sys
from pathlib import Path

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-public-key")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Compact-generation caps come from .env at request time; tests default to uncapped.
for _name in ("GENERATION_MAX_OBJECTIVES_PER_MODULE", "GENERATION_MAX_TASKS_PER_MODULE",
              "GENERATION_MAX_CHECKLIST_PER_MODULE", "GENERATION_MAX_QUIZ_PER_MODULE",
              "GENERATION_MAX_KEY_CONCEPTS_PER_MODULE", "GENERATION_MAX_ACTIVITIES_PER_MODULE",
              "GENERATION_MAX_SCENARIOS_PER_MODULE", "GENERATION_MAX_ASSESSMENTS_PER_MODULE",
              "GENERATION_MAX_COMPLETION_CRITERIA_PER_MODULE", "GENERATION_MAX_RUBRIC_ROWS",
              "GENERATION_MAX_TEXT_LENGTH"):
    os.environ[_name] = ""
# Short source keys are opt-in; tests default to today's 2.0.0 prompt regardless of .env.
os.environ["GENERATION_SOURCE_KEYS"] = "false"
os.environ["GENERATION_CONTENT_ONLY"] = "false"
# Tests never write the local diagnostics file unless a test points it at a temp path.
os.environ["GENERATION_DIAGNOSTICS_FILE"] = ""
