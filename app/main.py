import os
import random
from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func

from models import init_db, get_db, Question, Choice, Attempt, User
from auth import hash_password, verify_password, get_current_user

app = FastAPI(title="CertQuiz")

# SECRET_KEY signs the session cookie. Set this via the SESSION_SECRET env var
# in docker-compose.yml for a real deployment -- if it changes, everyone gets
# logged out (their existing session cookies no longer verify). The fallback
# below is fine for quick local testing but should NOT be relied on in your
# actual homelab deployment.
SECRET_KEY = os.environ.get("SESSION_SECRET", "dev-only-insecure-secret-change-me")

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Routes reachable without being logged in.
PUBLIC_PATHS = {"/login", "/register", "/setup"}


class RequireLoginMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path.startswith("/static") or path in PUBLIC_PATHS:
            return await call_next(request)

        db = next(get_db())
        try:
            user_count = db.query(User).count()
            # First-ever launch: no accounts exist yet, force account creation.
            if user_count == 0:
                if path != "/setup":
                    return RedirectResponse(url="/setup", status_code=303)
                return await call_next(request)

            # Accounts exist: require a valid session for everything else.
            if not request.session.get("user_id"):
                return RedirectResponse(url="/login", status_code=303)
        finally:
            db.close()

        return await call_next(request)


# Order matters: add_middleware wraps in REVERSE order of declaration (last
# added = outermost = runs first). We add RequireLoginMiddleware first so it
# ends up INSIDE SessionMiddleware -- meaning SessionMiddleware runs first
# and attaches request.session before our login check tries to read it.
app.add_middleware(RequireLoginMiddleware)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="certquiz_session")


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/setup", response_class=HTMLResponse)
def setup_form(request: Request, db: Session = Depends(get_db)):
    # If accounts already exist, setup is done -- don't let this be used to add more.
    if db.query(User).count() > 0:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "setup.html", {})


@app.post("/setup", response_class=HTMLResponse)
def setup_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    if db.query(User).count() > 0:
        return RedirectResponse(url="/login", status_code=303)

    username = username.strip()
    errors = []
    if not username:
        errors.append("Username is required.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if password != confirm_password:
        errors.append("Passwords don't match.")

    if errors:
        return templates.TemplateResponse(request, "setup.html", {"errors": errors, "prev_username": username})

    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)

    request.session["user_id"] = user.id
    request.session["username"] = user.username
    return RedirectResponse(url="/", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, db: Session = Depends(get_db)):
    if db.query(User).count() == 0:
        return RedirectResponse(url="/setup", status_code=303)
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {})


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    username = username.strip()
    user = db.query(User).filter(User.username == username).first()

    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request, "login.html", {"errors": ["Invalid username or password."], "prev_username": username}
        )

    request.session["user_id"] = user.id
    request.session["username"] = user.username
    return RedirectResponse(url="/", status_code=303)


@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    # Only reachable when already logged in (an existing user adding a
    # second account -- e.g. you adding Kenna's account after your own setup).
    if not request.session.get("user_id"):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "register.html", {})


@app.post("/register", response_class=HTMLResponse)
def register_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    if not request.session.get("user_id"):
        return RedirectResponse(url="/login", status_code=303)

    username = username.strip()
    errors = []
    if not username:
        errors.append("Username is required.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if password != confirm_password:
        errors.append("Passwords don't match.")
    if username and db.query(User).filter(User.username == username).first():
        errors.append("That username is already taken.")

    if errors:
        return templates.TemplateResponse(request, "register.html", {"errors": errors, "prev_username": username})

    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.commit()

    return templates.TemplateResponse(request, "register.html", {"success": True, "created_username": username})


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    certs = [row[0] for row in db.query(Question.cert).distinct().all()]
    return templates.TemplateResponse(
        request, "home.html", {"certs": certs}
    )


@app.get("/quiz", response_class=HTMLResponse)
def start_quiz(request: Request, cert: str = "All", count: int = 10, db: Session = Depends(get_db)):
    query = db.query(Question)
    if cert and cert != "All":
        query = query.filter(Question.cert == cert)

    all_ids = [q.id for q in query.all()]
    if not all_ids:
        return templates.TemplateResponse(
            request,
            "home.html",
            {
                "certs": [row[0] for row in db.query(Question.cert).distinct().all()],
                "error": f"No questions found for '{cert}'.",
            },
        )

    random.shuffle(all_ids)
    selected_ids = all_ids[: min(count, len(all_ids))]

    # Encode the quiz "session" as a comma-separated id list in the URL.
    # Simple and stateless -- no server-side session needed for a single-user app.
    id_string = ",".join(str(i) for i in selected_ids)
    return RedirectResponse(url=f"/question/0?ids={id_string}&score=0&cert={cert}", status_code=303)


@app.get("/question/{index}", response_class=HTMLResponse)
def show_question(index: int, request: Request, ids: str, score: int = 0, cert: str = "All", db: Session = Depends(get_db)):
    id_list = [int(i) for i in ids.split(",")]

    if index >= len(id_list):
        pct = round((score / len(id_list)) * 100) if id_list else 0
        return templates.TemplateResponse(
            request,
            "results.html",
            {"score": score, "total": len(id_list), "pct": pct, "cert": cert},
        )

    question_id = id_list[index]
    question = db.query(Question).filter(Question.id == question_id).first()
    choices = list(question.choices)
    random.shuffle(choices)

    return templates.TemplateResponse(
        request,
        "question.html",
        {
            "question": question,
            "choices": choices,
            "index": index,
            "total": len(id_list),
            "ids": ids,
            "score": score,
            "cert": cert,
        },
    )


@app.post("/answer", response_class=HTMLResponse)
def answer_question(
    request: Request,
    question_id: int = Form(...),
    choice_id: int = Form(...),
    index: int = Form(...),
    ids: str = Form(...),
    score: int = Form(...),
    cert: str = Form("All"),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)

    chosen = db.query(Choice).filter(Choice.id == choice_id).first()
    question = db.query(Question).filter(Question.id == question_id).first()
    correct_choice = next(c for c in question.choices if c.is_correct)

    was_correct = chosen.is_correct
    new_score = score + (1 if was_correct else 0)

    # Log the attempt so we can build a "missed questions" report later.
    attempt = Attempt(
        user_id=current_user.id if current_user else None,
        question_id=question_id,
        chosen_choice_id=choice_id,
        was_correct=was_correct,
    )
    db.add(attempt)
    db.commit()

    return templates.TemplateResponse(
        request,
        "feedback.html",
        {
            "question": question,
            "chosen": chosen,
            "correct_choice": correct_choice,
            "was_correct": was_correct,
            "index": index,
            "total": len(ids.split(",")),
            "ids": ids,
            "score": new_score,
            "cert": cert,
        },
    )


@app.get("/add-question", response_class=HTMLResponse)
def add_question_form(request: Request, db: Session = Depends(get_db)):
    certs = sorted({row[0] for row in db.query(Question.cert).distinct().all()})
    domains = sorted({row[0] for row in db.query(Question.domain).distinct().all() if row[0]})
    return templates.TemplateResponse(
        request,
        "add_question.html",
        {"certs": certs, "domains": domains},
    )


@app.post("/add-question", response_class=HTMLResponse)
async def add_question_submit(request: Request, db: Session = Depends(get_db)):
    form = await request.form()

    cert = (form.get("cert_existing") or "").strip()
    cert_new = (form.get("cert_new") or "").strip()
    final_cert = cert_new if cert_new else cert

    domain = (form.get("domain_existing") or "").strip()
    domain_new = (form.get("domain_new") or "").strip()
    final_domain = domain_new if domain_new else (domain or None)

    question_text = (form.get("question_text") or "").strip()
    explanation = (form.get("explanation") or "").strip() or None
    correct_index = form.get("correct_choice")

    # Choice text fields are named choice_0, choice_1, ... choice_5 in the template.
    # Collect any that were actually filled in -- the form supports up to 6 but
    # the user might only fill 2-4.
    choice_texts = []
    for i in range(6):
        val = (form.get(f"choice_{i}") or "").strip()
        choice_texts.append(val)

    errors = []
    if not final_cert:
        errors.append("Cert is required (pick one or type a new one).")
    if not question_text:
        errors.append("Question text is required.")

    filled_choices = [(i, t) for i, t in enumerate(choice_texts) if t]
    if len(filled_choices) < 2:
        errors.append("At least 2 answer choices are required.")
    if correct_index is None or correct_index == "":
        errors.append("You must mark one choice as correct.")
    elif int(correct_index) >= len(choice_texts) or not choice_texts[int(correct_index)].strip():
        errors.append("The choice marked correct must have text filled in.")

    if errors:
        certs = sorted({row[0] for row in db.query(Question.cert).distinct().all()})
        domains = sorted({row[0] for row in db.query(Question.domain).distinct().all() if row[0]})
        return templates.TemplateResponse(
            request,
            "add_question.html",
            {
                "certs": certs,
                "domains": domains,
                "errors": errors,
                # echo back what they typed so they don't have to redo it all
                "prev": {
                    "cert": final_cert,
                    "domain": final_domain,
                    "question_text": question_text,
                    "explanation": explanation,
                    "choices": choice_texts,
                    "correct_index": correct_index,
                },
            },
        )

    # Duplicate check, same rule as update_questions.py: exact match on cert + question_text.
    existing = (
        db.query(Question)
        .filter(Question.cert == final_cert, Question.question_text == question_text)
        .first()
    )
    if existing:
        certs = sorted({row[0] for row in db.query(Question.cert).distinct().all()})
        domains = sorted({row[0] for row in db.query(Question.domain).distinct().all() if row[0]})
        return templates.TemplateResponse(
            request,
            "add_question.html",
            {
                "certs": certs,
                "domains": domains,
                "errors": [f"A question with this exact text already exists under '{final_cert}'."],
                "prev": {
                    "cert": final_cert,
                    "domain": final_domain,
                    "question_text": question_text,
                    "explanation": explanation,
                    "choices": choice_texts,
                    "correct_index": correct_index,
                },
            },
        )

    q = Question(cert=final_cert, domain=final_domain, question_text=question_text, explanation=explanation)
    db.add(q)
    db.flush()

    correct_i = int(correct_index)
    for i, text in filled_choices:
        db.add(Choice(question_id=q.id, choice_text=text, is_correct=(i == correct_i)))

    db.commit()

    return templates.TemplateResponse(
        request,
        "add_question.html",
        {
            "certs": sorted({row[0] for row in db.query(Question.cert).distinct().all()}),
            "domains": sorted({row[0] for row in db.query(Question.domain).distinct().all() if row[0]}),
            "success": True,
            "added_cert": final_cert,
        },
    )


@app.get("/stats", response_class=HTMLResponse)
def stats(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    user_id = current_user.id if current_user else None

    base_query = db.query(Attempt).filter(Attempt.user_id == user_id)
    total_attempts = base_query.count()
    correct_attempts = base_query.filter(Attempt.was_correct == True).count()  # noqa: E712

    # Most-missed questions: count incorrect attempts per question, descending.
    # Scoped to this user's own attempts only -- not shared across accounts.
    missed = (
        db.query(Question, func.count(Attempt.id).label("miss_count"))
        .join(Attempt, Attempt.question_id == Question.id)
        .filter(Attempt.was_correct == False, Attempt.user_id == user_id)  # noqa: E712
        .group_by(Question.id)
        .order_by(func.count(Attempt.id).desc())
        .limit(10)
        .all()
    )

    pct = round((correct_attempts / total_attempts) * 100) if total_attempts else 0

    return templates.TemplateResponse(
        request,
        "stats.html",
        {
            "total_attempts": total_attempts,
            "correct_attempts": correct_attempts,
            "pct": pct,
            "missed": missed,
        },
    )
