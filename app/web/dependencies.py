"""Web 层共享依赖。"""

from pathlib import Path

from fastapi.templating import Jinja2Templates


templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)
