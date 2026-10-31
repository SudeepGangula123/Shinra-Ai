"""Entry point:  uvicorn app:app --host 0.0.0.0 --port 7860"""
import logging

from shinri.api import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
