import os
import sys
from pathlib import Path

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-public-key")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
