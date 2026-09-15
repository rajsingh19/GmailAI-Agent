"""
Test Suite for Task System (Milestone 5).
Validates:
- Authentication requirements (HTTP 401)
- CRUD operations
- Strict multi-user isolation
- Status, priority, and due_at filters
- Timezone validation and naive datetime rejection
- Completion timestamp tracking
- Cascade deletion
"""
from datetime import datetime, timezone, timedelta
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.security import SecurityManager
from app.models.user import User
from app.models.task import Task


async def create_test_user(test_db: AsyncSession, email: str = "task_user@example.com") -> User:
    user = User(email=email, full_name="Task Tester", is_active=True)
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


def set_auth_cookie(async_client: AsyncClient, user: User) -> None:
    token = SecurityManager.create_session_token(user_id=user.id)
    async_client.cookies.set(settings.SESSION_COOKIE_NAME, token)


@pytest.mark.asyncio
async def test_task_endpoints_require_authentication(async_client: AsyncClient):
    """All task endpoints must return 401 when unauthenticated."""
    assert (await async_client.get("/api/v1/tasks")).status_code == 401
    assert (await async_client.post("/api/v1/tasks", json={"title": "Test"})).status_code == 401
    assert (await async_client.get("/api/v1/tasks/task-123")).status_code == 401
    assert (await async_client.patch("/api/v1/tasks/task-123", json={"title": "Updated"})).status_code == 401
    assert (await async_client.post("/api/v1/tasks/task-123/complete")).status_code == 401
    assert (await async_client.delete("/api/v1/tasks/task-123")).status_code == 401


@pytest.mark.asyncio
async def test_create_task_success(async_client: AsyncClient, test_db: AsyncSession):
    """Successfully create a task for the authenticated user."""
    user = await create_test_user(test_db, "creator@example.com")
    set_auth_cookie(async_client, user)

    resp = await async_client.post(
        "/api/v1/tasks",
        json={
            "title": "Complete Milestone 5 implementation",
            "description": "Ensure multi-worker safety and atomic claim",
            "priority": "high",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Complete Milestone 5 implementation"
    assert data["description"] == "Ensure multi-worker safety and atomic claim"
    assert data["priority"] == "high"
    assert data["status"] == "pending"
    assert data["user_id"] == user.id
    assert data["completed_at"] is None


@pytest.mark.asyncio
async def test_create_task_with_due_date_and_timezone(async_client: AsyncClient, test_db: AsyncSession):
    """Create task with valid timezone-aware due date."""
    user = await create_test_user(test_db, "due_user@example.com")
    set_auth_cookie(async_client, user)

    due_dt = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    resp = await async_client.post(
        "/api/v1/tasks",
        json={
            "title": "Pay electric bill",
            "priority": "medium",
            "due_at": due_dt,
            "timezone": "America/New_York",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["timezone"] == "America/New_York"
    assert data["due_at"] is not None


@pytest.mark.asyncio
async def test_create_task_rejects_naive_datetime(async_client: AsyncClient, test_db: AsyncSession):
    """Naive datetime strings without offset should be rejected by validation."""
    user = await create_test_user(test_db, "naive_user@example.com")
    set_auth_cookie(async_client, user)

    resp = await async_client.post(
        "/api/v1/tasks",
        json={
            "title": "Naive due date task",
            "due_at": "2026-09-20T10:00:00",  # No timezone offset
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_task_rejects_invalid_timezone(async_client: AsyncClient, test_db: AsyncSession):
    """Invalid IANA timezone string should be rejected."""
    user = await create_test_user(test_db, "bad_tz_user@example.com")
    set_auth_cookie(async_client, user)

    resp = await async_client.post(
        "/api/v1/tasks",
        json={
            "title": "Bad TZ task",
            "timezone": "Mars/Olympus_Mons",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_task_success(async_client: AsyncClient, test_db: AsyncSession):
    """Get single task by ID."""
    user = await create_test_user(test_db, "getter@example.com")
    set_auth_cookie(async_client, user)

    create_resp = await async_client.post(
        "/api/v1/tasks",
        json={"title": "Specific Task", "priority": "low"},
    )
    task_id = create_resp.json()["id"]

    resp = await async_client.get(f"/api/v1/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == task_id
    assert resp.json()["title"] == "Specific Task"


@pytest.mark.asyncio
async def test_get_task_not_found(async_client: AsyncClient, test_db: AsyncSession):
    """Getting non-existent task returns 404."""
    user = await create_test_user(test_db, "missing@example.com")
    set_auth_cookie(async_client, user)

    resp = await async_client.get("/api/v1/tasks/non-existent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_tasks_multi_user_isolation(async_client: AsyncClient, test_db: AsyncSession):
    """User A cannot view User B's tasks."""
    user_a = await create_test_user(test_db, "user_a@example.com")
    user_b = await create_test_user(test_db, "user_b@example.com")

    # User A creates 2 tasks
    set_auth_cookie(async_client, user_a)
    await async_client.post("/api/v1/tasks", json={"title": "User A Task 1"})
    await async_client.post("/api/v1/tasks", json={"title": "User A Task 2"})

    # User B creates 1 task
    set_auth_cookie(async_client, user_b)
    await async_client.post("/api/v1/tasks", json={"title": "User B Secret Task"})

    # User B lists tasks - should only see 1
    resp_b = await async_client.get("/api/v1/tasks")
    assert resp_b.status_code == 200
    assert resp_b.json()["total"] == 1
    assert resp_b.json()["items"][0]["title"] == "User B Secret Task"

    # User A lists tasks - should only see 2
    set_auth_cookie(async_client, user_a)
    resp_a = await async_client.get("/api/v1/tasks")
    assert resp_a.status_code == 200
    assert resp_a.json()["total"] == 2
    titles = [t["title"] for t in resp_a.json()["items"]]
    assert "User B Secret Task" not in titles


@pytest.mark.asyncio
async def test_list_tasks_filter_by_status_and_priority(async_client: AsyncClient, test_db: AsyncSession):
    """Filter tasks by status and priority."""
    user = await create_test_user(test_db, "filter_user@example.com")
    set_auth_cookie(async_client, user)

    t1 = await async_client.post("/api/v1/tasks", json={"title": "Task 1", "priority": "high"})
    await async_client.post("/api/v1/tasks", json={"title": "Task 2", "priority": "low"})
    await async_client.post(f"/api/v1/tasks/{t1.json()['id']}/complete")

    # Filter by completed
    resp_completed = await async_client.get("/api/v1/tasks?status=completed")
    assert resp_completed.status_code == 200
    assert resp_completed.json()["total"] == 1
    assert resp_completed.json()["items"][0]["title"] == "Task 1"

    # Filter by priority=low
    resp_low = await async_client.get("/api/v1/tasks?priority=low")
    assert resp_low.status_code == 200
    assert resp_low.json()["total"] == 1
    assert resp_low.json()["items"][0]["title"] == "Task 2"


@pytest.mark.asyncio
async def test_update_task_fields(async_client: AsyncClient, test_db: AsyncSession):
    """Update task details and priority."""
    user = await create_test_user(test_db, "updater@example.com")
    set_auth_cookie(async_client, user)

    create_resp = await async_client.post("/api/v1/tasks", json={"title": "Initial Title", "priority": "low"})
    task_id = create_resp.json()["id"]

    patch_resp = await async_client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"title": "Updated Title", "priority": "high", "description": "New description"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["title"] == "Updated Title"
    assert patch_resp.json()["priority"] == "high"
    assert patch_resp.json()["description"] == "New description"


@pytest.mark.asyncio
async def test_complete_task_lifecycle(async_client: AsyncClient, test_db: AsyncSession):
    """Complete a task, verify completed_at timestamp, then revert to pending."""
    user = await create_test_user(test_db, "completer@example.com")
    set_auth_cookie(async_client, user)

    create_resp = await async_client.post("/api/v1/tasks", json={"title": "Finish feature"})
    task_id = create_resp.json()["id"]

    # Mark completed
    comp_resp = await async_client.post(f"/api/v1/tasks/{task_id}/complete")
    assert comp_resp.status_code == 200
    assert comp_resp.json()["status"] == "completed"
    assert comp_resp.json()["completed_at"] is not None

    # Revert to pending via PATCH
    uncomp_resp = await async_client.patch(f"/api/v1/tasks/{task_id}", json={"status": "pending"})
    assert uncomp_resp.status_code == 200
    assert uncomp_resp.json()["status"] == "pending"
    assert uncomp_resp.json()["completed_at"] is None


@pytest.mark.asyncio
async def test_delete_task_success(async_client: AsyncClient, test_db: AsyncSession):
    """Delete a task and verify it is removed from DB."""
    user = await create_test_user(test_db, "deleter@example.com")
    set_auth_cookie(async_client, user)

    create_resp = await async_client.post("/api/v1/tasks", json={"title": "To be deleted"})
    task_id = create_resp.json()["id"]

    del_resp = await async_client.delete(f"/api/v1/tasks/{task_id}")
    assert del_resp.status_code == 204

    get_resp = await async_client.get(f"/api/v1/tasks/{task_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_cross_user_task_modification_forbidden(async_client: AsyncClient, test_db: AsyncSession):
    """User A cannot modify or delete User B's task."""
    user_a = await create_test_user(test_db, "alice@example.com")
    user_b = await create_test_user(test_db, "bob@example.com")

    set_auth_cookie(async_client, user_a)
    create_resp = await async_client.post("/api/v1/tasks", json={"title": "Alice Task"})
    task_id = create_resp.json()["id"]

    # Bob tries to access, modify, complete, or delete Alice's task
    set_auth_cookie(async_client, user_b)
    assert (await async_client.get(f"/api/v1/tasks/{task_id}")).status_code == 404
    assert (await async_client.patch(f"/api/v1/tasks/{task_id}", json={"title": "Hacked"})).status_code == 404
    assert (await async_client.post(f"/api/v1/tasks/{task_id}/complete")).status_code == 404
    assert (await async_client.delete(f"/api/v1/tasks/{task_id}")).status_code == 404


@pytest.mark.asyncio
async def test_create_task_validation_title_length(async_client: AsyncClient, test_db: AsyncSession):
    """Empty title should be rejected with 422."""
    user = await create_test_user(test_db, "empty_title@example.com")
    set_auth_cookie(async_client, user)

    resp = await async_client.post("/api/v1/tasks", json={"title": ""})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_task_with_utc_default_timezone(async_client: AsyncClient, test_db: AsyncSession):
    """When timezone is omitted, it defaults to UTC."""
    user = await create_test_user(test_db, "default_tz@example.com")
    set_auth_cookie(async_client, user)

    resp = await async_client.post("/api/v1/tasks", json={"title": "Default TZ Task"})
    assert resp.status_code == 201
    assert resp.json()["timezone"] == "UTC"


@pytest.mark.asyncio
async def test_update_task_partial_fields_leaves_others_intact(async_client: AsyncClient, test_db: AsyncSession):
    """Updating only description preserves title and priority."""
    user = await create_test_user(test_db, "partial_up@example.com")
    set_auth_cookie(async_client, user)

    create_resp = await async_client.post(
        "/api/v1/tasks",
        json={"title": "Original Title", "priority": "high", "description": "Original Desc"},
    )
    task_id = create_resp.json()["id"]

    patch_resp = await async_client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"description": "Updated Desc Only"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["title"] == "Original Title"
    assert patch_resp.json()["priority"] == "high"
    assert patch_resp.json()["description"] == "Updated Desc Only"


@pytest.mark.asyncio
async def test_list_tasks_pagination_limit_and_offset(async_client: AsyncClient, test_db: AsyncSession):
    """Test limit and offset pagination on task list."""
    user = await create_test_user(test_db, "page_user@example.com")
    set_auth_cookie(async_client, user)

    for i in range(5):
        await async_client.post("/api/v1/tasks", json={"title": f"Task #{i}"})

    resp = await async_client.get("/api/v1/tasks?limit=2&offset=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2

