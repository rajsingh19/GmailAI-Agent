"""
Tests for Memory Delete Confirmation Safety & Token Verification (Milestone 11).
Contains exactly 10 tests verifying:
- delete_memory tool execution without token returns confirmation challenge
- Spoken words alone ("yes", "confirm") do not bypass confirmation challenge
- confirmed=True in arguments does not bypass confirmation challenge
- Valid server-issued confirmation token authorizes delete_memory
- Fake/forged confirmation token is rejected
- Expired confirmation token is rejected
- Replayed confirmation token is rejected (single-use challenge nonce)
- Cross-user confirmation token is rejected
- Wrong-tool confirmation token is rejected
- Wrong memory_id target token is rejected
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_preference import UserPreference
from app.schemas.memory import MemoryCreateRequest
from app.services.memory_service import MemoryService
from app.ai.agent.tool_executor import ToolExecutor
from app.ai.agent.confirmation import ConfirmationService


@pytest.fixture
async def conf_user(test_db: AsyncSession) -> User:
    user = User(id="user_conf_safety_1", email="conf_safety@example.com", is_active=True)
    test_db.add(user)
    pref = UserPreference(user_id=user.id, memory_enabled=True)
    test_db.add(pref)
    await test_db.commit()
    return user


@pytest.fixture
async def other_user(test_db: AsyncSession) -> User:
    user = User(id="user_conf_safety_2", email="conf_safety_other@example.com", is_active=True)
    test_db.add(user)
    pref = UserPreference(user_id=user.id, memory_enabled=True)
    test_db.add(pref)
    await test_db.commit()
    return user


@pytest.mark.asyncio
async def test_delete_memory_without_token_returns_confirmation_challenge(test_db: AsyncSession, conf_user: User):
    """1. Test delete_memory tool pauses and issues ConfirmationChallenge when token is absent."""
    req = MemoryCreateRequest(category="user_preference", key="lang.del", value="PHP", source="user_ui")
    mem = await MemoryService.create_or_upsert_memory(test_db, conf_user.id, req)

    res = await ToolExecutor.execute_tool(
        user_id=conf_user.id,
        db=test_db,
        tool_name="delete_memory",
        arguments={"memory_id": mem.id},
    )
    assert res.status == "confirmation_required"
    assert res.confirmation_challenge is not None
    assert res.confirmation_challenge.tool == "delete_memory"
    assert res.confirmation_challenge.target_id == mem.id
    assert res.confirmation_challenge.confirmation_token is not None


@pytest.mark.asyncio
async def test_spoken_words_do_not_bypass_confirmation(test_db: AsyncSession, conf_user: User):
    """2. Test passing verbal confirmation in arguments does not authorize deletion."""
    req = MemoryCreateRequest(category="user_preference", key="lang.del2", value="Perl", source="user_ui")
    mem = await MemoryService.create_or_upsert_memory(test_db, conf_user.id, req)

    res = await ToolExecutor.execute_tool(
        user_id=conf_user.id,
        db=test_db,
        tool_name="delete_memory",
        arguments={"memory_id": mem.id, "user_confirmed": "yes, please delete"},
    )
    assert res.status == "confirmation_required"


@pytest.mark.asyncio
async def test_confirmed_true_flag_does_not_bypass_token(test_db: AsyncSession, conf_user: User):
    """3. Test passing confirmed=True in arguments does not bypass challenge token requirement."""
    req = MemoryCreateRequest(category="user_preference", key="lang.del3", value="COBOL", source="user_ui")
    mem = await MemoryService.create_or_upsert_memory(test_db, conf_user.id, req)

    res = await ToolExecutor.execute_tool(
        user_id=conf_user.id,
        db=test_db,
        tool_name="delete_memory",
        arguments={"memory_id": mem.id, "confirmed": True},
    )
    assert res.status == "confirmation_required"


@pytest.mark.asyncio
async def test_valid_confirmation_token_executes_deletion(test_db: AsyncSession, conf_user: User):
    """4. Test that supplying a valid server-issued token successfully deletes the memory."""
    req = MemoryCreateRequest(category="user_preference", key="lang.del4", value="Fortran", source="user_ui")
    mem = await MemoryService.create_or_upsert_memory(test_db, conf_user.id, req)

    # 1. Obtain challenge token
    challenge_token = ConfirmationService.issue_challenge(
        user_id=conf_user.id,
        tool_name="delete_memory",
        target_id=mem.id,
        action="delete",
    )

    # 2. Execute with token
    res = await ToolExecutor.execute_tool(
        user_id=conf_user.id,
        db=test_db,
        tool_name="delete_memory",
        arguments={"memory_id": mem.id},
        confirmation_token=challenge_token,
    )
    assert res.status == "completed"
    assert res.is_error is False

    # 3. Verify memory deleted from DB
    check = await MemoryService.get_memory(test_db, conf_user.id, mem.id)
    assert check is None


@pytest.mark.asyncio
async def test_fake_confirmation_token_rejected(test_db: AsyncSession, conf_user: User):
    """5. Test fake forged confirmation token is rejected and re-issues challenge."""
    req = MemoryCreateRequest(category="user_preference", key="lang.del5", value="Ada", source="user_ui")
    mem = await MemoryService.create_or_upsert_memory(test_db, conf_user.id, req)

    res = await ToolExecutor.execute_tool(
        user_id=conf_user.id,
        db=test_db,
        tool_name="delete_memory",
        arguments={"memory_id": mem.id},
        confirmation_token="fake.forged.token.payload",
    )
    assert res.status == "confirmation_required"


@pytest.mark.asyncio
async def test_expired_confirmation_token_rejected(test_db: AsyncSession, conf_user: User):
    """6. Test expired confirmation token is rejected."""
    req = MemoryCreateRequest(category="user_preference", key="lang.del6", value="Pascal", source="user_ui")
    mem = await MemoryService.create_or_upsert_memory(test_db, conf_user.id, req)

    expired_token = ConfirmationService.issue_challenge(
        user_id=conf_user.id,
        tool_name="delete_memory",
        target_id=mem.id,
        action="delete",
        ttl_seconds=-10,  # Already expired
    )

    res = await ToolExecutor.execute_tool(
        user_id=conf_user.id,
        db=test_db,
        tool_name="delete_memory",
        arguments={"memory_id": mem.id},
        confirmation_token=expired_token,
    )
    assert res.status == "confirmation_required"


@pytest.mark.asyncio
async def test_replayed_confirmation_token_rejected(test_db: AsyncSession, conf_user: User):
    """7. Test replaying an already consumed confirmation token is rejected."""
    req = MemoryCreateRequest(category="user_preference", key="lang.del7", value="Haskell", source="user_ui")
    mem = await MemoryService.create_or_upsert_memory(test_db, conf_user.id, req)

    token = ConfirmationService.issue_challenge(
        user_id=conf_user.id,
        tool_name="delete_memory",
        target_id=mem.id,
        action="delete",
    )

    # First execution succeeds
    res1 = await ToolExecutor.execute_tool(
        user_id=conf_user.id,
        db=test_db,
        tool_name="delete_memory",
        arguments={"memory_id": mem.id},
        confirmation_token=token,
    )
    assert res1.status == "completed"

    # Replay attempt fails and re-issues challenge
    res2 = await ToolExecutor.execute_tool(
        user_id=conf_user.id,
        db=test_db,
        tool_name="delete_memory",
        arguments={"memory_id": mem.id},
        confirmation_token=token,
    )
    assert res2.status == "confirmation_required"


@pytest.mark.asyncio
async def test_cross_user_confirmation_token_rejected(test_db: AsyncSession, conf_user: User, other_user: User):
    """8. Test token issued for User A is rejected when executed by User B."""
    req = MemoryCreateRequest(category="user_preference", key="lang.del8", value="Elixir", source="user_ui")
    mem = await MemoryService.create_or_upsert_memory(test_db, other_user.id, req)

    token_a = ConfirmationService.issue_challenge(
        user_id=conf_user.id,
        tool_name="delete_memory",
        target_id=mem.id,
        action="delete",
    )

    res = await ToolExecutor.execute_tool(
        user_id=other_user.id,
        db=test_db,
        tool_name="delete_memory",
        arguments={"memory_id": mem.id},
        confirmation_token=token_a,
    )
    assert res.status == "confirmation_required"


@pytest.mark.asyncio
async def test_wrong_tool_confirmation_token_rejected(test_db: AsyncSession, conf_user: User):
    """9. Test token issued for delete_task cannot be used for delete_memory."""
    req = MemoryCreateRequest(category="user_preference", key="lang.del9", value="Clojure", source="user_ui")
    mem = await MemoryService.create_or_upsert_memory(test_db, conf_user.id, req)

    task_token = ConfirmationService.issue_challenge(
        user_id=conf_user.id,
        tool_name="delete_task",  # Wrong tool
        target_id=mem.id,
        action="delete",
    )

    res = await ToolExecutor.execute_tool(
        user_id=conf_user.id,
        db=test_db,
        tool_name="delete_memory",
        arguments={"memory_id": mem.id},
        confirmation_token=task_token,
    )
    assert res.status == "confirmation_required"


@pytest.mark.asyncio
async def test_wrong_target_memory_token_rejected(test_db: AsyncSession, conf_user: User):
    """10. Test token issued for memory_1 cannot be used to delete memory_2."""
    req1 = MemoryCreateRequest(category="user_preference", key="lang.del10a", value="Erlang", source="user_ui")
    req2 = MemoryCreateRequest(category="user_preference", key="lang.del10b", value="Lua", source="user_ui")
    mem1 = await MemoryService.create_or_upsert_memory(test_db, conf_user.id, req1)
    mem2 = await MemoryService.create_or_upsert_memory(test_db, conf_user.id, req2)

    token_mem1 = ConfirmationService.issue_challenge(
        user_id=conf_user.id,
        tool_name="delete_memory",
        target_id=mem1.id,
        action="delete",
    )

    res = await ToolExecutor.execute_tool(
        user_id=conf_user.id,
        db=test_db,
        tool_name="delete_memory",
        arguments={"memory_id": mem2.id},  # Target mismatch
        confirmation_token=token_mem1,
    )
    assert res.status == "confirmation_required"
