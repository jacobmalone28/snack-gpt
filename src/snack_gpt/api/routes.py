"""Web and API routes for Phase 2 - Review Interface."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from snack_gpt.db import get_db
from snack_gpt.services.auth import PasswordManager, SessionManager
from snack_gpt.services.backup import BackupManager
from snack_gpt.services.export import DataExporter
from snack_gpt.services.totals import DailyTotalsCalculator

router = APIRouter()

# Dependency for database
DbSession = Annotated[Session, Depends(get_db)]


def get_authenticated_profile(request: Request) -> int:
    """
    Extract and validate session from request.

    Returns:
        Profile ID if authenticated.

    Raises:
        HTTPException if not authenticated.
    """
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    profile_id = SessionManager.validate_session(session_token)
    if profile_id is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    return profile_id


AuthProfile = Annotated[int, Depends(get_authenticated_profile)]


@router.post("/auth/login")
async def login(password: str, response: Response) -> dict[str, str]:
    """
    Authenticate with admin password.

    Args:
        password: Admin password.
        response: FastAPI response object to set cookies.

    Returns:
        Success message if authenticated.

    Raises:
        HTTPException if password is incorrect.
    """
    if not PasswordManager.verify_password(password):
        raise HTTPException(status_code=401, detail="Invalid password")

    # Create session for default profile (ID=1)
    session_token = SessionManager.create_session(profile_id=1)
    response.set_cookie("session_token", session_token, httponly=True, secure=False)

    return {"status": "authenticated", "session_token": session_token}


@router.post("/auth/logout")
async def logout(request: Request, response: Response) -> dict[str, str]:
    """Log out the current session."""
    session_token = request.cookies.get("session_token")
    if session_token:
        SessionManager.invalidate_session(session_token)
        response.delete_cookie("session_token")

    return {"status": "logged_out"}


@router.get("/api/daily-total", response_model=dict)
async def get_daily_total(db: DbSession, profile_id: AuthProfile, target_date: date = date.today()) -> dict[str, object]:
    """Get daily nutrition totals and targets."""
    confirmed, _, has_pending = DailyTotalsCalculator.get_daily_total(db, profile_id, target_date)
    target = DailyTotalsCalculator.get_daily_target(db, profile_id, target_date)

    return {
        "date": target_date.isoformat(),
        "confirmed": {
            "calories": confirmed.calories,
            "protein": confirmed.protein,
            "carbohydrate": confirmed.carbohydrate,
            "fat": confirmed.fat,
            "fiber": confirmed.fiber,
        },
        "target": {
            "calories": target.calories,
            "protein": target.protein,
            "carbohydrate": target.carbohydrate,
            "fat": target.fat,
            "fiber": target.fiber,
        } if target else None,
        "has_pending": has_pending,
    }


@router.get("/api/export/history.json")
async def export_history_json(db: DbSession, profile_id: AuthProfile) -> Response:
    """Export consumption history as JSON."""
    json_content = DataExporter.export_consumption_history_json(db, profile_id)
    return Response(
        content=json_content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=consumption_history.json"},
    )


@router.get("/api/export/history.csv")
async def export_history_csv(db: DbSession, profile_id: AuthProfile) -> Response:
    """Export consumption history as CSV."""
    csv_content = DataExporter.export_consumption_history_csv(db, profile_id)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=consumption_history.csv"},
    )


@router.get("/api/export/foods.json")
async def export_foods_json(db: DbSession, profile_id: AuthProfile) -> Response:
    """Export food database as JSON."""
    json_content = DataExporter.export_food_database_json(db, profile_id)
    return Response(
        content=json_content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=foods.json"},
    )


@router.get("/api/export/targets.json")
async def export_targets_json(db: DbSession, profile_id: AuthProfile) -> Response:
    """Export daily targets as JSON."""
    json_content = DataExporter.export_daily_targets_json(db, profile_id)
    return Response(
        content=json_content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=daily_targets.json"},
    )


@router.get("/api/backups")
async def list_backups() -> dict[str, object]:
    """List available database backups."""
    manager = BackupManager()
    backups = manager.list_backups()
    return {"backups": backups}


@router.post("/api/backups")
async def create_backup_endpoint() -> dict[str, object]:
    """Create a new database backup."""
    manager = BackupManager()
    backup_path = manager.create_backup()

    if not backup_path:
        raise HTTPException(status_code=500, detail="Failed to create backup")

    return {"backup_path": str(backup_path), "status": "created"}


@router.post("/api/backups/restore")
async def restore_backup_endpoint(backup_path: str) -> dict[str, object]:
    """Restore from a backup."""
    from pathlib import Path

    manager = BackupManager()
    path = Path(backup_path)

    if not manager.verify_backup(path):
        raise HTTPException(status_code=400, detail="Invalid or corrupt backup")

    if not manager.restore_backup(path):
        raise HTTPException(status_code=500, detail="Failed to restore backup")

    return {"status": "restored", "backup_path": backup_path}
