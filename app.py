import os
from flask import Flask, request, render_template, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.utils import secure_filename
import fitz
from functions import *
import shutil
import tempfile
from flask import send_file, session
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    login_required,
    logout_user,
)
from flask_bcrypt import Bcrypt
from functools import wraps


app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"
app.config["ALLOWED_EXTENSIONS"] = {"pdf"}
app.secret_key = "SECRETT_KEY"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///screener_app.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)
bcrypt = Bcrypt(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=False, unique=True)
    email = db.Column(db.String(150), nullable=False, unique=True)
    password = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(50), default="user")


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def role_required(required_role):

    def decorator(f):
        @wraps(f)
        def wrapped_function(*args, **kwargs):
            if "role" not in session or session["role"] != required_role:
                flash("Access denied. Insufficient permissions!", "danger")
                return redirect(url_for("upload_files"))
            return f(*args, **kwargs)

        return wrapped_function

    return decorator


class Users(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(250), unique=True, nullable=False)
    password = db.Column(db.String(250), nullable=False)


class Position(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    criteria = db.relationship(
        "Criteria", back_populates="position", cascade="all, delete-orphan"
    )


class Criteria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(365), nullable=False)
    position_id = db.Column(db.Integer, db.ForeignKey("position.id"), nullable=False)
    criteria_type = db.Column(db.Integer, nullable=False)
    score = db.Column(db.Integer, nullable=False)
    position = db.relationship("Position", back_populates="criteria")


def clear_uploads_folder():
    folder = app.config["UPLOAD_FOLDER"]
    if os.path.exists(folder):
        shutil.rmtree(folder)  # Remove all files and subdirectories
    os.makedirs(folder, exist_ok=True)  # Recreate an empty folder


clear_uploads_folder()

with app.app_context():
    db.create_all()

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]
    )


def extract_text_from_pdf(file_path):
    pdf = fitz.open(file_path)
    final_text = [pdf[page_number].get_text() for page_number in range(len(pdf))]
    return "\n".join(final_text)


@app.route("/users", methods=["GET"])
@login_required
@role_required("admin")
def users():
    users = User.query.all()
    users = [user for user in users if user.id != session["user_id"]]
    return render_template("users.html", users=users)


@app.route("/users/delete/<int:user_id>", methods=["POST"])
@login_required
@role_required("admin")
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    return redirect(url_for("users"))


@app.route("/register", methods=["GET", "POST"])
@login_required
@role_required("admin")
def register():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        role = request.form.get("role")

        # Hash password
        hashed_password = bcrypt.generate_password_hash(password).decode("utf-8")

        # Create user and add to DB
        new_user = User(
            username=username, email=email, password=hashed_password, role=role
        )
        db.session.add(new_user)
        db.session.commit()

        flash("Account created successfully!", "success")
        return redirect(url_for("users"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        # Verify user
        user = User.query.filter_by(email=email).first()
        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            session["role"] = user.role
            session["user_id"] = user.id
            return redirect(url_for("upload_files"))
        else:
            flash("Login failed. Check email and password.", "danger")
            return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    session.pop("role", None)
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/positions/add", methods=["GET", "POST"])
@login_required
@role_required("admin")
def add_position():
    if request.method == "POST":

        position_name = request.form.get("position-name")
        min_qualifications = request.form.getlist("min-qualifications[]")
        pref_qualifications = request.form.getlist("pref-qualifications[]")
        added_value = request.form.getlist("added-value[]")
        min_qualification_score = request.form.get("min-qualification-score")
        pref_qualification_score = request.form.get("pref-qualification-score")
        added_value_qualification_score = request.form.get(
            "added-value-qualification-score"
        )

        if not position_name.strip():
            flash("Criteria name cannot be empty!", "danger")
            return redirect(url_for("create_position"))  # Redirect back to the form
        else:
            new_position = Position(name=position_name)
            db.session.add(new_position)
            db.session.commit()

            for min_criteria in min_qualifications:
                criteria = Criteria(
                    description=min_criteria,
                    position_id=new_position.id,
                    criteria_type=1,
                    score=int(min_qualification_score),
                )
                db.session.add(criteria)

            for pref_criteria in pref_qualifications:
                criteria = Criteria(
                    description=pref_criteria,
                    position_id=new_position.id,
                    criteria_type=2,
                    score=int(pref_qualification_score),
                )
                db.session.add(criteria)

            for added_criteria in added_value:
                criteria = Criteria(
                    description=added_criteria,
                    position_id=new_position.id,
                    criteria_type=3,
                    score=int(added_value_qualification_score),
                )
                db.session.add(criteria)
            db.session.commit()
            return redirect(url_for("get_position"))

    return render_template("create_position.html")


def sync_criteria(
    existing_criteria, new_descriptions, criteria_type, position_id, score
):
    # Mark existing criteria as handled
    handled_ids = set()

    # Update existing criteria or add new ones
    for i, description in enumerate(new_descriptions):
        if i < len(existing_criteria):
            # Update existing criteria
            criteria = existing_criteria[i]
            criteria.description = description.strip()
            criteria.criteria_type = criteria_type
            criteria.score = score
            handled_ids.add(criteria.id)
        else:
            # Add new criteria
            new_criteria = Criteria(
                description=description.strip(),
                criteria_type=criteria_type,
                position_id=position_id,
                score=score,
            )
            db.session.add(new_criteria)

    # Remove criteria not present in the new list
    for criteria in existing_criteria:
        if criteria.id not in handled_ids:
            db.session.delete(criteria)


@login_required
@role_required("admin")
@app.route("/positions/edit/<int:position_id>", methods=["GET", "POST"])
def edit_position(position_id):
    # Fetch position and associated criteria
    position = Position.query.get_or_404(position_id)
    min_criteria = Criteria.query.filter_by(
        position_id=position_id, criteria_type=1
    ).all()

    pref_criteria = Criteria.query.filter_by(
        position_id=position_id, criteria_type=2
    ).all()
    added_value = Criteria.query.filter_by(
        position_id=position_id, criteria_type=3
    ).all()

    if request.method == "POST":
        # Update position name
        position.name = request.form["position-name"]

        # Update Minimum Qualifications
        min_criteria_descriptions = request.form.getlist("min-qualifications[]")
        min_criteria_score = request.form.get("min-qualification-score", type=int)

        # Sync database with form data for minimum criteria
        sync_criteria(
            min_criteria, min_criteria_descriptions, 1, position.id, min_criteria_score
        )

        # Update Preferred Qualifications
        pref_criteria_descriptions = request.form.getlist("pref-qualifications[]")
        pref_criteria_score = request.form.get("pref-qualification-score", type=int)

        sync_criteria(
            pref_criteria,
            pref_criteria_descriptions,
            2,
            position.id,
            pref_criteria_score,
        )

        # Update Added Value
        added_value_descriptions = request.form.getlist("added-value[]")
        added_value_score = request.form.get(
            "added-value-qualification-score", type=int
        )

        sync_criteria(
            added_value, added_value_descriptions, 3, position.id, added_value_score
        )

        # Commit changes to the database
        db.session.commit()

        # Redirect to the positions list (or any relevant page)
        return redirect(url_for("get_position"))

    # Render the edit form
    return render_template(
        "edit_position.html",
        position=position,
        min_criteria=min_criteria,
        pref_criteria=pref_criteria,
        added_value=added_value,
    )


@app.route("/positions/delete/<int:position_id>", methods=["POST"])
@login_required
@role_required("admin")
def delete_position(position_id):
    position = Position.query.get_or_404(position_id)
    db.session.delete(position)
    db.session.commit()
    return redirect(url_for("get_position"))


@app.route("/positions", methods=["GET"])
@login_required
@role_required("admin")
def get_position():
    positions = Position.query.all()
    return render_template("positions.html", positions=positions)


@app.route("/download", methods=["GET"])
@login_required
def download_results():
    # Get position_name from query parameters
    position_name = request.args.get("position_name")
    if not position_name:
        flash("Position name is missing for download.", "danger")
        return redirect(url_for("upload_files"))

    temp_dir = tempfile.gettempdir()
    output_path = os.path.join(temp_dir, f"{position_name} Screening Result.xlsx")

    # Check if the file exists before sending
    if not os.path.exists(output_path):
        flash(
            "Requested file not found. Please try generating results again.", "danger"
        )
        return redirect(url_for("upload_files"))

    return send_file(
        output_path,
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        download_name=f"{position_name} Screening Result.xlsx",
    )


@app.route("/", methods=["GET", "POST"])
@login_required
def upload_files():
    if request.method == "POST":
        position_id = request.form.get("position-id")
        position_name = Position.query.get(position_id).name
        criteria_list = Criteria.query.filter_by(position_id=position_id).all()
        min_qualifications = [
            criteria.description
            for criteria in criteria_list
            if criteria.criteria_type == 1
        ]
        pref_qualifications = [
            criteria.description
            for criteria in criteria_list
            if criteria.criteria_type == 2
        ]
        added_value = [
            criteria.description
            for criteria in criteria_list
            if criteria.criteria_type == 3
        ]

        min_qualification_score = [
            criteria.score for criteria in criteria_list if criteria.criteria_type == 1
        ][0]

        pref_qualification_score = [
            criteria.score for criteria in criteria_list if criteria.criteria_type == 2
        ][0]

        added_value_score = [
            criteria.score for criteria in criteria_list if criteria.criteria_type == 3
        ][0]

        qualification_score = {
            "Minimum Qualification": min_qualification_score,
            "Preferred Qualification": pref_qualification_score,
            "Added Value": added_value_score,
        }

        if "files[]" not in request.files:
            flash("No file part", "danger")
            return redirect(request.url)

        files = request.files.getlist("files[]")

        if not files or files[0].filename == "":
            flash("No files selected!", "danger")
            return redirect(request.url)

        for file in files:
            if not file.filename.endswith(".pdf"):
                flash("Select only pdf files", "danger")
                return redirect(request.url)

        merged_score = []
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(filepath)

                # Extract text and calculate match score
                resume_text = extract_text_from_pdf(filepath)
                resume_data = preprocess_resume(resume_text)
                results = check_requirements(
                    resume_data=resume_data,
                    min_qualifications=min_qualifications,
                    pref_qualifications=pref_qualifications,
                    added_value=added_value,
                )
                score = get_score(results, qualification_score=qualification_score)
                score["File Name"] = [filename]
                merged_score.append(score)
        final_result = pd.concat(merged_score)

        # Save Excel file to a temporary location
        temp_dir = tempfile.gettempdir()
        output_path = os.path.join(temp_dir, f"{position_name} Screening Result.xlsx")
        final_result.to_excel(output_path)

        return render_template(
            "results.html",
            final_result=final_result,
            download_url=url_for("download_results", position_name=position_name),
            position_name=position_name,
        )
    positions = Position.query.all()
    return render_template("index.html", positions=positions)


if __name__ == "__main__":
    app.run(debug=True)
