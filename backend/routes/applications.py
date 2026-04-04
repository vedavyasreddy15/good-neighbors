# ─── What this file does ──────────────────────────────────────────────────────
# Handles the "Apply" flow — the core action of the whole platform.
#
# Endpoints:
#   POST /api/applications/{gig_id}   — artist hits Apply on a gig
#   GET  /api/applications/{gig_id}   — business sees who applied to their gig
#   GET  /api/applications/mine       — artist sees all gigs they've applied to
#
# The whole philosophy here: no forms, no friction.
# An artist's profile already has everything a business needs to decide.
# Applying is just writing one row to the applications table.
# That's it.
# ──────────────────────────────────────────────────────────────────────────────

from fastapi import APIRouter, Depends, HTTPException, status

from db.connection import get_pool
from services.auth import get_current_user, require_role

router = APIRouter()


@router.post("/{gig_id}", status_code=status.HTTP_201_CREATED)
async def apply_to_gig(
    gig_id: str,
    current_user: dict = Depends(require_role("artist")),
):
    """
    Artist applies to a gig. One click — no form.
    The UNIQUE constraint in the DB prevents double-applying.
    """
    pool = get_pool()
    artist_id = current_user["user_id"]

    async with pool.acquire() as conn:
        # Make sure the gig exists and is still open
        gig = await conn.fetchrow(
            "SELECT id, status FROM gigs WHERE id = $1", gig_id
        )
        if not gig:
            raise HTTPException(status_code=404, detail="Gig not found.")
        if gig["status"] != "open":
            raise HTTPException(status_code=409, detail="This gig is no longer accepting applications.")

        try:
            await conn.execute(
                """
                INSERT INTO applications (gig_id, artist_id)
                VALUES ($1, $2)
                """,
                gig_id, artist_id,
            )
        except Exception:
            # The UNIQUE(gig_id, artist_id) constraint fires if they already applied
            raise HTTPException(status_code=409, detail="You've already applied to this gig.")

    return {"message": "Applied successfully."}


@router.get("/mine")
async def my_applications(current_user: dict = Depends(require_role("artist"))):
    """
    Artist sees all the gigs they've applied to, with current status.
    """
    pool = get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT a.id, a.status, a.applied_at,
                   g.title, g.category, g.pay, g.location, g.date,
                   bp.business_name
            FROM applications a
            JOIN gigs g ON g.id = a.gig_id
            JOIN business_profiles bp ON bp.user_id = g.business_id
            WHERE a.artist_id = $1
            ORDER BY a.applied_at DESC
            """,
            current_user["user_id"],
        )

    return {"applications": [dict(r) for r in rows]}


@router.get("/gig/{gig_id}")
async def gig_applicants(
    gig_id: str,
    current_user: dict = Depends(require_role("business")),
):
    """
    Business sees everyone who applied to one of their gigs.
    Returns each artist's profile info so the business can decide.
    """
    pool = get_pool()

    async with pool.acquire() as conn:
        # Confirm this gig belongs to this business
        gig = await conn.fetchrow(
            "SELECT business_id FROM gigs WHERE id = $1", gig_id
        )
        if not gig or str(gig["business_id"]) != current_user["user_id"]:
            raise HTTPException(status_code=403, detail="Not your gig.")

        rows = await conn.fetch(
            """
            SELECT a.id AS application_id, a.status, a.applied_at,
                   ap.user_id, ap.display_name, ap.category, ap.skills,
                   ap.location, ap.gig_count, ap.instagram, ap.portfolio_url
            FROM applications a
            JOIN artist_profiles ap ON ap.user_id = a.artist_id
            WHERE a.gig_id = $1
            ORDER BY a.applied_at ASC
            """,
            gig_id,
        )

    return {"applicants": [dict(r) for r in rows]}


@router.patch("/{application_id}/approve")
async def approve_application(
    application_id: str,
    current_user: dict = Depends(require_role("business")),
):
    """
    Business approves an application.
    Sends a notification to the artist.
    """
    pool = get_pool()

    async with pool.acquire() as conn:
        # Confirm this application belongs to a gig owned by this business
        app_row = await conn.fetchrow(
            """
            SELECT a.artist_id, g.id AS gig_id, g.title, g.business_id
            FROM applications a
            JOIN gigs g ON g.id = a.gig_id
            WHERE a.id = $1
            """,
            application_id
        )
        if not app_row or str(app_row["business_id"]) != current_user["user_id"]:
            raise HTTPException(status_code=403, detail="Not authorized to approve this application.")
        
        await conn.execute("UPDATE applications SET status = 'approved' WHERE id = $1", application_id)
        
        # Notify the artist
        await conn.execute(
            """
            INSERT INTO notifications (user_id, type, title, message, link)
            VALUES ($1, 'application_approved', 'Application Approved!', $2, $3)
            """,
            app_row["artist_id"],
            f"Your application for '{app_row['title']}' has been approved!",
            f"/artist" 
        )

    return {"message": "Application approved successfully."}
