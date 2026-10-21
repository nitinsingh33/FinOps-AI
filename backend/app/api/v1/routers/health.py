from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health/live")
def liveness():
    return {"status": "ok"}


@router.get("/health/ready")
def readiness():
    from app.db.session import engine
    try:
        with engine.connect() as conn:
            conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        return {"status": "ready", "database": "connected"}
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "database": "disconnected", "detail": str(exc)},
        )
