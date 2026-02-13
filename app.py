import os
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-key")

# SQLite lưu trong thư mục instance
os.makedirs(app.instance_path, exist_ok=True)
DB_PATH = os.path.join(app.instance_path, "app.db")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + DB_PATH.replace("\\", "/")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

ADMIN_USERS = {"hoangminh"}  # đổi thành username admin của bạn

COURSES = [
    {"slug": "toan-10", "title": "Toán 10"},
    {"slug": "toan-11", "title": "Toán 11"},
    {"slug": "toan-12-on-thi-thpt", "title": "Toán 12 - Ôn thi THPT"},
    {"slug": "luyen-de", "title": "Luyện đề THPTQG"},
]

# Mã nhập học (bạn tự đổi)
COURSE_CODES = {
    "toan-10": "MA_TOAN10_2026",
    "toan-11": "MA_TOAN11_2026",
    "toan-12-on-thi-thpt": "MA_TOAN12_2026",
    "luyen-de": "MA_LUYEN_DE_2026",
}

# Nội dung tài liệu (bạn thay url tại đây)
COURSE_CONTENTS = {
    "toan-10": {"sections": [
        {"title": "Chung", "items": [{"label": "Lộ trình", "url": "https://example.com/toan10/lo-trinh"}]},
    ]},
    "toan-11": {"sections": [
        {"title": "Chung", "items": [{"label": "Lộ trình", "url": "https://example.com/toan11/lo-trinh"}]},
    ]},
    "toan-12-on-thi-thpt": {"sections": [
        {"title": "Chung", "items": [{"label": "Lộ trình", "url": "https://example.com/toan12/lo-trinh"}]},
    ]},
    "luyen-de": {"sections": [
        {"title": "Chung", "items": [{"label": "Lộ trình", "url": "https://example.com/luyen-de/lo-trinh"}]},
    ]},
}


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(255), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Enrollment(db.Model):
    __tablename__ = "enrollments"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    course_slug = db.Column(db.String(80), nullable=False, index=True)
    unlocked_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("user_id", "course_slug", name="uq_user_course"),)


class Score(db.Model):
    __tablename__ = "scores"
    id = db.Column(db.Integer, primary_key=True)
    course_slug = db.Column(db.String(80), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    assignment = db.Column(db.String(255), nullable=False)
    score = db.Column(db.Float, nullable=False)
    max_score = db.Column(db.Float, nullable=False)
    note = db.Column(db.Text, nullable=True)
    graded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


with app.app_context():
    db.create_all()


def is_admin() -> bool:
    return (session.get("username") or "") in ADMIN_USERS


@app.context_processor
def inject_globals():
    # dùng trong base.html để hiện tab "Nhập điểm"
    return dict(ADMIN_USERS=ADMIN_USERS, is_admin=is_admin)


def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)
    return wrapper


def get_user_by_username(username: str):
    return User.query.filter_by(username=username).first()


def is_enrolled(course_slug: str, user_id: int) -> bool:
    return Enrollment.query.filter_by(user_id=user_id, course_slug=course_slug).first() is not None


def add_enrollment(course_slug: str, user_id: int):
    if is_enrolled(course_slug, user_id):
        return
    db.session.add(Enrollment(user_id=user_id, course_slug=course_slug, unlocked_at=datetime.utcnow()))
    db.session.commit()


def get_my_enrolled_slugs(user_id: int) -> set:
    rows = Enrollment.query.filter_by(user_id=user_id).all()
    return {r.course_slug for r in rows}


def list_scores(course_slug: str, user_id: int):
    rows = Score.query.filter_by(course_slug=course_slug, user_id=user_id).order_by(Score.graded_at.desc()).all()
    return [{
        "assignment": r.assignment,
        "score": r.score,
        "max_score": r.max_score,
        "note": r.note or "",
        "graded_at": r.graded_at.isoformat(timespec="seconds")
    } for r in rows]


def add_score(course_slug: str, user_id: int, assignment: str, score: float, max_score: float, note: str = ""):
    db.session.add(Score(
        course_slug=course_slug,
        user_id=user_id,
        assignment=assignment,
        score=float(score),
        max_score=float(max_score),
        note=note.strip() if note else ""
    ))
    db.session.commit()


# ===== Auth =====
@app.get("/login")
def login():
    if session.get("user_id"):
        return redirect(url_for("home"))
    return render_template("auth.html", active_tab="login", active_auth="login")


@app.post("/login")
def login_post():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    if not username or not password:
        flash("Vui lòng nhập tài khoản và mật khẩu.", "error")
        return redirect(url_for("login"))

    user = get_user_by_username(username)
    if not user:
        flash("Tài khoản không tồn tại.", "error")
        return redirect(url_for("login"))

    if not check_password_hash(user.password_hash, password):
        flash("Mật khẩu không đúng.", "error")
        return redirect(url_for("login"))

    session["user_id"] = user.id
    session["username"] = user.username
    session["full_name"] = user.full_name
    flash("Đăng nhập thành công.", "success")
    return redirect(url_for("home"))


@app.get("/register")
def register():
    if session.get("user_id"):
        return redirect(url_for("home"))
    return render_template("auth.html", active_tab="register", active_auth="register")


@app.post("/register")
def register_post():
    full_name = (request.form.get("full_name") or "").strip()
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    confirm = request.form.get("confirm") or ""

    if not full_name or not username or not password:
        flash("Vui lòng nhập đầy đủ thông tin đăng ký.", "error")
        return redirect(url_for("register"))

    if password != confirm:
        flash("Mật khẩu xác nhận không khớp.", "error")
        return redirect(url_for("register"))

    if get_user_by_username(username):
        flash("Tên đăng nhập đã tồn tại.", "error")
        return redirect(url_for("register"))

    user = User(
        username=username,
        full_name=full_name,
        password_hash=generate_password_hash(password),
        created_at=datetime.utcnow()
    )
    db.session.add(user)
    db.session.commit()

    session["user_id"] = user.id
    session["username"] = user.username
    session["full_name"] = user.full_name
    flash("Đăng ký thành công.", "success")
    return redirect(url_for("home"))


@app.get("/logout")
def logout():
    session.clear()
    flash("Đã đăng xuất.", "success")
    return redirect(url_for("login"))


# ===== Pages =====
@app.get("/")
@login_required
def home():
    return render_template("index.html", active="home")


@app.get("/khoa-hoc")
@login_required
def khoa_hoc():
    user_id = session["user_id"]
    my_slugs = get_my_enrolled_slugs(user_id)

    courses_view = []
    for c in COURSES:
        courses_view.append({
            "slug": c["slug"],
            "title": c["title"],
            "state": "mine" if c["slug"] in my_slugs else "available"
        })

    return render_template("khoa-hoc.html", courses=courses_view, active="khoa_hoc")


@app.post("/unlock/<slug>")
@login_required
def unlock_course(slug: str):
    code = ""
    if request.is_json:
        code = (request.json.get("code") or "").strip()
    else:
        code = (request.form.get("code") or "").strip()

    valid_slugs = {c["slug"] for c in COURSES}
    if slug not in valid_slugs:
        return jsonify({"ok": False, "message": "Khóa học không tồn tại."}), 404

    expected = COURSE_CODES.get(slug, "")
    if not expected or code != expected:
        return jsonify({"ok": False, "message": "Mã nhập học không đúng."}), 400

    add_enrollment(slug, session["user_id"])
    return jsonify({"ok": True, "redirect": url_for("course_page", slug=slug)})


@app.get("/course/<slug>")
@login_required
def course_page(slug: str):
    valid_slugs = {c["slug"] for c in COURSES}
    if slug not in valid_slugs:
        flash("Khóa học không tồn tại.", "error")
        return redirect(url_for("khoa_hoc"))

    user_id = session["user_id"]
    if not is_enrolled(slug, user_id):
        flash("Bạn cần nhập mã để mở khóa khóa học này.", "error")
        return redirect(url_for("khoa_hoc"))

    course_title = next(c["title"] for c in COURSES if c["slug"] == slug)
    contents = COURSE_CONTENTS.get(slug, {"sections": []})
    scores = list_scores(slug, user_id)

    return render_template(
        "course.html",
        course_slug=slug,
        course_title=course_title,
        sections=contents.get("sections", []),
        scores=scores,
        active="khoa_hoc"
    )


@app.get("/teacher/scores")
@login_required
def teacher_scores():
    if not is_admin():
        flash("Bạn không có quyền truy cập trang này.", "error")
        return redirect(url_for("home"))

    recent_rows = (
        db.session.query(Score, User)
        .join(User, User.id == Score.user_id)
        .order_by(Score.graded_at.desc())
        .limit(30)
        .all()
    )

    recent = []
    for sc, u in recent_rows:
        recent.append({
            "course_slug": sc.course_slug,
            "username": u.username,
            "assignment": sc.assignment,
            "score": sc.score,
            "max_score": sc.max_score,
            "note": sc.note or "",
            "graded_at": sc.graded_at.isoformat(timespec="seconds")
        })

    return render_template("teacher_scores.html", courses=COURSES, recent=recent, active="teacher_scores")


@app.post("/teacher/scores")
@login_required
def teacher_scores_post():
    if not is_admin():
        return redirect(url_for("home"))

    course_slug = (request.form.get("course_slug") or "").strip()
    username = (request.form.get("username") or "").strip()
    assignment = (request.form.get("assignment") or "").strip()
    score = (request.form.get("score") or "").strip()
    max_score = (request.form.get("max_score") or "").strip()
    note = (request.form.get("note") or "").strip()

    if not course_slug or not username or not assignment or not score or not max_score:
        flash("Vui lòng nhập đủ: khóa học, username, tên bài, điểm, điểm tối đa.", "error")
        return redirect(url_for("teacher_scores"))

    # ✅ kiểm tra username học sinh tồn tại
    stu = get_user_by_username(username)
    if not stu:
        flash("Username học sinh chưa tồn tại. Yêu cầu học sinh đăng ký/đăng nhập trước.", "error")
        return redirect(url_for("teacher_scores"))

    try:
        s = float(score)
        ms = float(max_score)
    except:
        flash("Điểm phải là số.", "error")
        return redirect(url_for("teacher_scores"))

    add_score(course_slug, stu.id, assignment, s, ms, note)
    flash("Đã lưu điểm.", "success")
    return redirect(url_for("teacher_scores"))


@app.get("/lien-he")
@login_required
def lien_he():
    return render_template("lien-he.html", active="lien_he")


if __name__ == "__main__":
    app.run(debug=True)
