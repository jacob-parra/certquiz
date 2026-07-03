"""
update_questions.py

Adds new questions from seed_questions.json to the database WITHOUT wiping
existing data or attempt history. Unlike seed.py (which only runs on an
empty DB), this script is meant to be run anytime you've added new
questions to the JSON file.

Duplicate detection: a question is considered "already in the DB" if there's
an existing row with the SAME cert AND the SAME question_text (exact string
match, case-sensitive). If you edit/fix the wording of an existing question
in the JSON, this script will NOT recognize it as the same question -- it
will add it as a new entry instead. If that happens, just delete the old
duplicate manually (see README for a DB inspection snippet).

Usage:
    DB_PATH=/path/to/certquiz.db python3 update_questions.py
    DB_PATH=/path/to/certquiz.db python3 update_questions.py --file my_new_questions.json
"""

import argparse
import json
import os
from models import init_db, SessionLocal, Question, Choice

DEFAULT_SEED_FILE = os.path.join(os.path.dirname(__file__), "data", "seed_questions.json")


def load_questions(path):
    with open(path) as f:
        return json.load(f)


def update(file_path):
    init_db()
    db = SessionLocal()
    added = 0
    skipped = 0

    try:
        data = load_questions(file_path)

        # Build a set of (cert, question_text) pairs already in the DB
        # so we only need one query instead of one per question.
        existing = db.query(Question.cert, Question.question_text).all()
        existing_keys = set(existing)

        for item in data:
            key = (item["cert"], item["question_text"])

            if key in existing_keys:
                skipped += 1
                continue

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

            existing_keys.add(key)  # avoid re-adding if duplicated within the same JSON file
            added += 1

        db.commit()
        print(f"Added {added} new question(s). Skipped {skipped} already-existing question(s).")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add new questions to the DB without wiping existing data.")
    parser.add_argument(
        "--file",
        default=DEFAULT_SEED_FILE,
        help="Path to the JSON file of questions (default: app/data/seed_questions.json)",
    )
    args = parser.parse_args()
    update(args.file)
