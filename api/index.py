import sys
import os

# Add backend directory to sys.path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# On Vercel serverless functions, the root is read-only.
# Default SQLite database to /tmp if DATABASE_URL is not explicitly configured.
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "sqlite:////tmp/pipeline_gas.db"

# Set frontend directory environment variable
if "FRONTEND_DIR" not in os.environ:
    os.environ["FRONTEND_DIR"] = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))

# Import the FastAPI application
from app.main import app
