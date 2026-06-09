"""Database engine + session factory. SQLAlchemy 2.0 style."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
import config


class Base(DeclarativeBase):
    pass


engine = create_engine(
    config.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session():
    """Yield a session (FastAPI dependency / context use)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all():
    # Import models so they register on Base before create_all.
    import db.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
