import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Application configuration"""
    
    # API
    API_TITLE = "ezLogic API"
    API_VERSION = "0.1.0"
    
    # Anthropic
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    
    # Lean
    LEAN_PATH = os.getenv("LEAN_PATH", "lean")
    PROOFS_DIR = os.getenv("PROOFS_DIR", "./proofs")
    
    # Frontend
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
    
    # Ensure proofs directory exists
    @classmethod
    def ensure_proofs_dir(cls):
        os.makedirs(cls.PROOFS_DIR, exist_ok=True)

# Initialize
Config.ensure_proofs_dir()
