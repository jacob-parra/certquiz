# CertQuiz

A self-hosted multiple-choice quiz app for CompTIA cert practice (Security+, Network+, PenTest+, etc).
FastAPI backend, server-rendered HTML (no JS framework), SQLite for storage. Comes with over 500 questions, across Security+, Network+ and Pentest+. (235 Security +, 115 Pentest +, 200 Network +)

## What's been tested

Features
- Home page loads and lists certs from the DB
- Starting a quiz randomly selects N questions and redirects into the quiz flow
- Questions render with shuffled answer choices
- Submitting an answer logs the attempt, shows correct/incorrect + explanation
- Stats page loads (including the empty state), scoped per logged-in user
- Adding a question via the in-app form (`/add-question`), including duplicate rejection and validation errors
- `update_questions.py` adds only new questions from a JSON file without touching existing data or attempt history
- First-launch flow: no accounts exist → forced to `/setup` → account created → auto-logged-in
- Login gating: every route except `/login`, `/register`, `/setup`, and `/static` requires a valid session
- Multiple accounts: registered a second account while logged in, confirmed its stats start empty and stay separate from the first account's
- Wrong password rejected; `/setup` locked out once an account exists (even via direct POST)
- Logout actually clears the session cookie (confirmed by reusing the post-logout cookie and getting redirected to `/login`)
- Passwords are bcrypt-hashed in the database, not stored in plaintext
- Migration path: ran the app against an existing pre-auth database (no `users` table, no `user_id` on `attempts`) and confirmed it adds the missing column automatically without losing any existing questions or attempt history


## Project structure

```
certquiz/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── app/
    ├── main.py              # FastAPI routes (quiz, add-question, auth)
    ├── models.py            # SQLAlchemy models (User, Question, Choice, Attempt) + DB migration logic
    ├── auth.py              # Password hashing/verification, current-user session lookup
    ├── seed.py              # Loads seed_questions.json into an empty DB (idempotent)
    ├── update_questions.py  # Adds new questions from JSON without wiping existing data
    ├── data/
    │   └── seed_questions.json   # Starter question bank, edit/extend this
    ├── templates/           # Jinja2 HTML templates
    │   ├── base.html
    │   ├── home.html
    │   ├── question.html
    │   ├── feedback.html
    │   ├── results.html
    │   ├── stats.html
    │   ├── add_question.html
    │   ├── setup.html       # First-launch account creation
    │   ├── login.html
    │   └── register.html    # Add additional accounts while logged in
    └── static/
        └── style.css
```

## Assembly steps

### 1. Local test run (no Docker) — confirms the app itself works on your machine

```bash
cd certquiz/app
pip install -r ../requirements.txt --break-system-packages   # or use a venv
DB_PATH=./certquiz.db python3 seed.py
DB_PATH=./certquiz.db uvicorn main:app --host 0.0.0.0 --port 8000
```

Visit `http://localhost:8000`. You should see the cert dropdown and a "Start Quiz" button.

### 2. Docker build

```bash
cd certquiz
docker compose build
docker compose up -d
```

Visit `http://localhost:8000` (or wherever you've mapped the port).

Check logs if anything looks wrong:
```bash
docker compose logs -f certquiz
```

### 3. Deploying into your homelab

Suggested Implementation
- Run this as its own LXC on Proxmox (lightweight, just needs Docker + Compose), OR
- Add it as another container on a host that's already running Docker Compose stacks
- Use a reverse proxy (like nginx) for TLS termination and HTTPS
- Since it's single-user and low-traffic, no need for anything fancier than the bind-mounted volume already in `docker-compose.yml`

### 4. Accounts and login

The app now requires logging in. The very first time you launch it (no accounts exist yet), it'll take you straight to an account-creation page — whatever username/password you set there becomes the first account and you're auto-logged-in afterward.

**Adding more accounts :** once you're logged in, click **"Add Account"** in the nav bar (`/register`). Each account has its own separate quiz stats and attempt history — nothing is shared between accounts.

**Session length:** logging in keeps you signed in for that browser session — closing the browser ends it, so you'll need to log in again next time. This was a deliberate choice over a long-lived "remember me" cookie.

**Before deploying to your homelab**, change the `SESSION_SECRET` in `docker-compose.yml` from the placeholder to a real random value:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```
Paste the output in as `SESSION_SECRET=...`. This secret signs the login session cookie — if you skip this and leave the default placeholder, anyone who got a copy of this repo could in theory forge a valid session cookie for your instance. If you ever change `SESSION_SECRET` later, everyone gets logged out (existing cookies stop validating), which is expected.

**Upgrading from a database created before login existed:** if you already have a `certquiz.db` from before this feature was added (no `users` table, no `user_id` on attempts), the app handles this automatically — on startup it detects the old schema and adds the missing `user_id` column to your existing `attempts` table without touching your existing questions or attempt history. Pre-existing attempts will just have no associated user (they predate accounts), and you'll be sent through the first-time setup flow to create your first account, same as a brand new database.

### 5. Adding your own questions

You have two ways to add questions: **directly in the app** (easiest, no file editing) or **via JSON files** (better for bulk adds or scripting).

#### Option A: In-app "Add Question" page

Click **"Add Question"** in the nav bar, or go to `/add-question`. The form lets you:
- Pick an existing cert from a dropdown, or type a new one to create it on the fly
- Same for domain (optional)
- Fill in question text, 2-6 answer choices, mark which one is correct
- Add an optional explanation shown after answering

It writes straight to the database — no file editing, no rebuild, no restart needed. Duplicate questions (same cert + exact question text) are rejected with a message telling you so, same rule as the JSON-based workflow below.

#### Option B: JSON file + update script

Edit `app/data/seed_questions.json` (or create a separate JSON file) — it's a plain JSON array, each question looks like:

```json
{
  "cert": "Security+",
  "domain": "Threats, Attacks & Vulnerabilities",
  "question_text": "...",
  "explanation": "...",
  "choices": [
    {"text": "...", "correct": true},
    {"text": "...", "correct": false}
  ]
}
```

Once you've added new questions to the JSON, run `update_questions.py` to add just the new ones without touching existing questions or your attempt history:

**Locally:**
```bash
cd certquiz/app
DB_PATH=./certquiz.db python3 update_questions.py
```

**In Docker:**
```bash
docker compose exec certquiz python3 update_questions.py
```

You can also point it at a separate file instead of editing `seed_questions.json` directly, e.g. if you want to keep a running file of newly-added questions:
```bash
python3 update_questions.py --file data/my_new_questions.json
```

**How it detects duplicates:** a question is skipped if there's already a row in the DB with the exact same `cert` and `question_text` (case-sensitive, exact string match). This means:
- Adding genuinely new questions works as expected.
- If you go back and **edit the wording** of an existing question in the JSON, the script won't recognize it as the same question — it'll add it as a new entry instead, leaving the old one in place. If that happens, delete the stale duplicate manually:
  ```bash
  python3 -c "
  from models import SessionLocal, Question
  db = SessionLocal()
  q = db.query(Question).filter(Question.id == <old_id>).first()
  db.delete(q)
  db.commit()
  "
  ```

If you ever do want a full wipe-and-reseed instead (e.g. starting over from scratch), that's still the volume-removal approach:
```bash
docker compose down
docker volume rm certquiz_certquiz-data
docker compose up -d
```
This wipes attempt history too — `update_questions.py` is the one to reach for day-to-day.

## What needs more work (be aware of these before you rely on this)


1. **Auth is basic, by design, for a homelab tool** — login uses a server-side session cookie (good), and passwords are bcrypt-hashed (good), but there's no rate-limiting on login attempts, no account lockout, no password reset flow, and no "forgot password" — if you forget a password, you'd need to reset it directly in the database (see snippet below). This is appropriate for a personal/family tool behind Tailscale or your LAN, but don't treat it as production-grade auth if you ever expose this beyond your network.

   To manually reset a password if needed:
   ```bash
   docker compose exec certquiz python3 -c "
   from models import SessionLocal, User
   from auth import hash_password
   db = SessionLocal()
   user = db.query(User).filter(User.username == '<username').first()
   user.password_hash = hash_password('new-password-here')
   db.commit()
   "
   ```

2. **Quiz "state" still travels via URL, not session** — which questions you're on and your running score are passed as URL query params (`?ids=1,2,3&score=2`), same as before login was added. This is unrelated to *who* you are (that part's now properly gated by the session cookie), it's just *how far into a quiz* you are. Practically this means: the quiz state is visible/editable in the URL bar, and if you bookmark or share a mid-quiz URL, someone else logged into the app could theoretically open it and it'd record an attempt under *their* account, not yours. Not a real risk for personal use, but worth knowing.

3. **Editing existing question wording isn't detected** — `update_questions.py` matches on exact `cert` + `question_text`. If you tweak the wording of a question already in the DB, it'll be treated as new rather than updating the original. See the README section above for how to manually remove the stale duplicate if this happens.

4. **No domain-level filtering in the quiz UI** — the seed data tags each question with a `domain` (e.g. "Threats, Attacks & Vulnerabilities"), but the quiz start page only filters by `cert`, not by domain. Easy to add later: another dropdown on the home page, another filter clause in `start_quiz()`.

5. **No HTTPS in the container itself** — recommended to use Caddy or Nginx for TLS termination and HTTPS.
