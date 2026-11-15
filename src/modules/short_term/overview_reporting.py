"""Use the installed skill's deterministic report engine in PanWatch too."""
from functools import lru_cache
import importlib.util

from src.modules.administration.builtin_skills import SKILLS_PATH


@lru_cache(maxsize=1)
def engine():
    path = SKILLS_PATH / 'analyze-a-share-sentiment/scripts/render_report.py'
    spec = importlib.util.spec_from_file_location('panwatch_sentiment_report', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
