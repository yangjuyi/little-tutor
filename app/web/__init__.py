"""little-tutor Web 应用装配。"""

from fastapi import FastAPI

from app.web.student import router as student_router
from app.web.teacher import router as teacher_router


app = FastAPI(title="little-tutor 演示版")
app.include_router(student_router)
app.include_router(teacher_router)
