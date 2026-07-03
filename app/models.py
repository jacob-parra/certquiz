from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship, sessionmaker, declarative_base
from datetime import datetime, timezone
import os

DB_PATH = os.environ.get("DB_PATH", "/data/certquiz.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    cert = Column(String, index=True, nullable=False)       # e.g. "Security+"
    domain = Column(String, index=True, nullable=True)       # e.g. "Threats, Attacks & Vulnerabilities"
    question_text = Column(String, nullable=False)
    explanation = Column(String, nullable=True)

    choices = relationship("Choice", back_populates="question", cascade="all, delete-orphan")


class Choice(Base):
    __tablename__ = "choices"

    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    choice_text = Column(String, nullable=False)
    is_correct = Column(Boolean, default=False, nullable=False)

    question = relationship("Question", back_populates="choices")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Attempt(Base):
    __tablename__ = "attempts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # nullable for pre-existing rows from before login was added
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    chosen_choice_id = Column(Integer, ForeignKey("choices.id"), nullable=False)
    was_correct = Column(Boolean, nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _migrate_add_user_id_to_attempts()


def _migrate_add_user_id_to_attempts():
    """
    Lightweight migration for existing databases created before login was added.
    Base.metadata.create_all() only creates tables that don't exist yet -- it
    won't add new columns to a table that's already there. If you're running
    this against a fresh/new database, the attempts table is created with
    user_id already included by the model above, and this is a no-op.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "attempts" not in inspector.get_table_names():
        return  # table doesn't exist yet, nothing to migrate

    columns = [col["name"] for col in inspector.get_columns("attempts")]
    if "user_id" not in columns:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE attempts ADD COLUMN user_id INTEGER REFERENCES users(id)"))
            conn.commit()
        print("Migrated: added user_id column to existing attempts table.")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
