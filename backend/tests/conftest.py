import pytest
from typing import AsyncGenerator
from httpx import ASGITransport, AsyncClient
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app

# Ensure mock credentials are populated for test suite
settings.GOOGLE_CLIENT_ID = "mock-client-id.apps.googleusercontent.com"
settings.GOOGLE_CLIENT_SECRET = "mock-client-secret-xyz123"
settings.TOKEN_ENCRYPTION_KEY = ""
settings.SECRET_KEY = "test-secret-key-32-bytes-minimum-length-strictly"


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def test_engine():
    """Isolated in-memory SQLite engine for unit tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False,
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def test_db(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provides a transactional database session for tests."""
    async_session = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with async_session() as session:
        yield session


@pytest.fixture
async def async_client(test_db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client fixture with database dependency override."""
    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:8000") as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
async def pg_session() -> AsyncGenerator[AsyncSession, None]:
    """Provides a session connected to the real PostgreSQL database."""
    pg_url = settings.DATABASE_URL
    if not pg_url.startswith("postgresql"):
        pg_url = "postgresql+asyncpg://ai_user:ai_password@localhost:5438/ai_assistant"

    engine = create_async_engine(pg_url, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()

