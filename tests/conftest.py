"""pytest bootstrap: never call real LLM/DB from developer .env."""

import os

os.environ["APP_ENV"] = "testing"
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["INTENT_BACKEND"] = "deepseek"
os.environ["JEV_API_KEY"] = ""
os.environ["CROSS_ENCODER_FORCE"] = "false"
os.environ["LOCAL_EMBEDDING_FORCE"] = "false"
os.environ["UNSTRUCTURED_FORCE"] = "false"
os.environ["EMBEDDING_API_KEY"] = ""
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./data/local/test.db"
os.environ["REDIS_URL"] = ""
os.environ["QDRANT_URL"] = ""
os.environ["LOG_LEVEL"] = "WARNING"

from pathlib import Path

Path("data/local").mkdir(parents=True, exist_ok=True)
