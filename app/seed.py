import json
import os
from models import init_db, SessionLocal, Question, Choice

SEED_FILE = os.path.join(os.path.dirname(__file__), "data", "seed_questions.json")


def seed():
    init_db()
    db = SessionLocal()
    try:
        existing_count = db.query(Question).count()
        if existing_count > 0:
            print(f"Database already has {existing_count} questions. Skipping seed.")
            print("Delete the .db file (or the volume) if you want to reseed from scratch.")
            return

        with open(SEED_FILE) as f:
            data = json.load(f)

        for item in data:
            q = Question(
                cert=item["cert"],
                domain=item.get("domain"),
                question_text=item["question_text"],
                explanation=item.get("explanation"),
            )
            db.add(q)
            db.flush()  # get q.id before adding choices

            for c in item["choices"]:
                choice = Choice(
                    question_id=q.id,
                    choice_text=c["text"],
                    is_correct=c["correct"],
                )
                db.add(choice)

        db.commit()
        print(f"Seeded {len(data)} questions.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
