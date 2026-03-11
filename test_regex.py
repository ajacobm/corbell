import re
from pathlib import Path

content = Path('/Users/himmi/github/corbel/specgen_local/src/supabase_orchestrator.py').read_text()
vars = re.findall(
    r'(?:process\.env\.|os\.getenv\(|os\.environ\[|os\.environ\.get\(|System\.getenv\(|os\.Getenv\(|envvar=)\s*'
    r'["\']?([A-Z_][A-Z0-9_]*)["\']?',
    content
)
print("Extracted vars:", vars)
