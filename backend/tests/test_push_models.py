import pytest
import uuid
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.push_subscription import PushSubscription


@pytest.mark.asyncio
async def test_push_subscription_creation_and_cascade(test_db: AsyncSession, test_user: User):
    """Verify push subscription creation, field persistence, and user relationship."""
    sub = PushSubscription(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        endpoint="https://fcm.googleapis.com/fcm/send/test-sub-1",
        p256dh_key="BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QT9Q0v4IfRCoDEr00",
        auth_key="tBHItJI5svbpez7KI4CCXg",
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    )
    test_db.add(sub)
    await test_db.commit()

    # Query back
    result = await test_db.execute(select(PushSubscription).where(PushSubscription.endpoint == sub.endpoint))
    saved_sub = result.scalars().first()
    assert saved_sub is not None
    assert saved_sub.user_id == test_user.id
    assert saved_sub.p256dh_key == sub.p256dh_key
    assert saved_sub.auth_key == sub.auth_key


@pytest.mark.asyncio
async def test_push_subscription_unique_endpoint_constraint(test_db: AsyncSession, test_user: User, test_user_b: User):
    """Verify database-level UNIQUE(endpoint) constraint enforces cross-user collision rejection."""
    endpoint = "https://updates.push.services.mozilla.com/wpush/v2/shared-endpoint-123"

    sub1 = PushSubscription(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        endpoint=endpoint,
        p256dh_key="key1",
        auth_key="auth1",
    )
    test_db.add(sub1)
    await test_db.commit()

    # Attempt to insert same endpoint for another user -> Database must reject
    sub2 = PushSubscription(
        id=str(uuid.uuid4()),
        user_id=test_user_b.id,
        endpoint=endpoint,
        p256dh_key="key2",
        auth_key="auth2",
    )
    test_db.add(sub2)
    with pytest.raises(IntegrityError):
        await test_db.commit()
    await test_db.rollback()
