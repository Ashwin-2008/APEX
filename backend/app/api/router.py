from fastapi import APIRouter

from app.api.routes import attempts, questions, students
from app.api.routes import predictions, progress, health, recommendations
from app.api.routes import research
from app.api.routes import project_reviews
from app.api.routes import auth, projects, notifications

api_router = APIRouter()
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(projects.router, tags=["projects"])
api_router.include_router(notifications.router, tags=["notifications"])
api_router.include_router(students.router, tags=["students"])
api_router.include_router(questions.router, tags=["questions"])
api_router.include_router(attempts.router, tags=["attempts"])
api_router.include_router(predictions.router, tags=["predictions"])
api_router.include_router(recommendations.router, tags=["recommendations"])
api_router.include_router(progress.router, tags=["progress"])
api_router.include_router(health.router, tags=["health"])
api_router.include_router(research.router)
api_router.include_router(project_reviews.router, tags=["project-reviews"])
