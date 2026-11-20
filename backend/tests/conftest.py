import sys
from pathlib import Path

# Make backend modules (graph, agent, config) importable when running `pytest` from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
