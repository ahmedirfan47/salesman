"""Pytest fixtures.

Uses a REAL Postgres test database, not SQLite -- the app's models use
Postgres-specific UUID columns and `SELECT ... FOR UPDATE` locking, so an
SQLite substitute would not exercise the same code paths.

Set TEST_DATABASE_URL to point at a throwaway database. Defaults to a local
`salesman_test` db. Every test gets a clean schema.
"""
import os

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
# Importing the models package registers every model on Base.metadata.
import app.db.models  # noqa: F401

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://salesman:salesman@127.0.0.1:5432/salesman_test",
)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(TEST_DATABASE_URL)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()