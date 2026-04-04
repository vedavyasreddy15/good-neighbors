from fastapi import APIRouter, Depends
from db.connection import get_pool
from services.auth import get_current_user

router = APIRouter()

@router.get("/")
async def get_notifications(current_user: dict = Depends(get_current_user)):
    """Get all notifications for the current user."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, type, title, message, link, is_read, created_at
            FROM notifications
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT 50
            """,
            current_user["user_id"]
        )
    return {"notifications": [dict(r) for r in rows]}

@router.patch("/{notification_id}/read")
async def mark_notification_read(notification_id: str, current_user: dict = Depends(get_current_user)):
    """Mark a notification as read."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE notifications SET is_read = TRUE WHERE id = $1 AND user_id = $2",
            notification_id, current_user["user_id"]
        )
    return {"message": "Notification marked as read."}

@router.patch("/read-all")
async def mark_all_read(current_user: dict = Depends(get_current_user)):
    """Mark all notifications as read for the user."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE notifications SET is_read = TRUE WHERE user_id = $1", current_user["user_id"])
    return {"message": "All notifications marked as read."}