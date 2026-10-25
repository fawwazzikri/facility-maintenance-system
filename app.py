
from flask import (
    Flask, render_template_string, request, redirect,
    url_for, send_from_directory, abort, session, flash
)
from functools import wraps
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
import sqlite3
import os
import uuid
import json
import secrets

app = Flask(__name__)

# =====================================
# 1. CONFIGURATION AND SECURITY
# =====================================

secret_key = os.environ.get("SECRET_KEY")

if not secret_key:
    if os.environ.get("RENDER"):
        raise RuntimeError("SECRET_KEY is missing from Render.")
    secret_key = secrets.token_hex(32)

app.secret_key = secret_key
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(
    os.environ.get("RENDER")
)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

try:
    ADMIN_ACCOUNTS = json.loads(
        os.environ.get("ADMIN_ACCOUNTS", "{}")
    )
except json.JSONDecodeError:
    raise RuntimeError("ADMIN_ACCOUNTS must contain valid JSON.")

if not isinstance(ADMIN_ACCOUNTS, dict):
    raise RuntimeError("ADMIN_ACCOUNTS must be a JSON object.")

DATABASE = os.path.join(app.root_path, "maintenance.db")
UPLOAD_FOLDER = os.path.join(app.root_path, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

ALLOWED_STATUSES = [
    "Pending", "In Progress", "Waiting Parts",
    "Completed", "Closed"
]
ALLOWED_PRIORITIES = ["Low", "Medium", "High"]
TECHNICIANS = ["Technician A", "Technician B", "Technician C"]
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


# =====================================
# 2. ACCESS CONTROL
# =====================================

def admin_required(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        if "admin_username" not in session:
            return redirect(url_for("admin_login", next=request.path))
        return view_function(*args, **kwargs)
    return wrapped_view


def valid_internal_path(path):
    return (
        isinstance(path, str)
        and path.startswith("/")
        and not path.startswith("//")
        and "\\" not in path
    )


# =====================================
# 3. DATABASE
# =====================================

def get_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def create_database():
    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter TEXT,
            location TEXT,
            damage TEXT,
            description TEXT,
            date_reported TEXT,
            status TEXT DEFAULT 'Pending'
        )
    """)

    columns = {
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(complaints)"
        ).fetchall()
    }

    if "technician" not in columns:
        conn.execute(
            "ALTER TABLE complaints ADD COLUMN technician TEXT"
        )

    if "priority" not in columns:
        conn.execute(
            "ALTER TABLE complaints "
            "ADD COLUMN priority TEXT DEFAULT 'Medium'"
        )

    if "photo_path" not in columns:
        conn.execute(
            "ALTER TABLE complaints ADD COLUMN photo_path TEXT"
        )

    conn.commit()
    conn.close()


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )


def save_uploaded_photo(photo):
    if not photo or not photo.filename:
        return None

    safe_name = secure_filename(photo.filename)

    if not safe_name or not allowed_file(safe_name):
        raise ValueError("Use JPG, JPEG, PNG or WEBP images only.")

    data = photo.stream.read(5 * 1024 * 1024 + 1)

    if len(data) > 5 * 1024 * 1024:
        raise ValueError("Image must be 5 MB or smaller.")

    extension = safe_name.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{extension}"
    destination = os.path.join(UPLOAD_FOLDER, filename)

    with open(destination, "wb") as image_file:
        image_file.write(data)

    return filename


# =====================================
# 4. COMMON WEBSITE DESIGN
# =====================================

STYLE = """
<style>
* { box-sizing: border-box; }

body {
    font-family: Arial, sans-serif;
    background: #f3f5f9;
    margin: 0;
    color: #263244;
}

header {
    background: #17365d;
    color: white;
    padding: 22px;
    text-align: center;
}

nav {
    background: #244a73;
    padding: 12px;
    text-align: center;
}

nav a {
    color: white;
    text-decoration: none;
    margin: 6px 10px;
    display: inline-block;
    font-weight: bold;
}

main {
    max-width: 1250px;
    margin: 28px auto;
    padding: 0 18px;
}

.card {
    background: white;
    padding: 20px;
    border-radius: 10px;
    box-shadow: 0 2px 8px #00000012;
    margin-bottom: 18px;
}

.dashboard {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(185px, 1fr));
    gap: 16px;
    margin: 20px 0;
}

.stat {
    display: block;
    color: #263244;
    text-decoration: none;
}

.stat:hover { transform: translateY(-2px); }
.stat h3 { font-size: 16px; }

.number {
    font-size: 34px;
    font-weight: bold;
    color: #17365d;
}

.hint, .muted {
    color: #667085;
    font-size: 13px;
}

label {
    display: block;
    margin-top: 12px;
    font-weight: bold;
}

input, textarea, select {
    width: 100%;
    padding: 10px;
    margin-top: 6px;
    border: 1px solid #ccd3dd;
    border-radius: 5px;
}

button, .button {
    display: inline-block;
    background: #1769aa;
    color: white;
    border: 0;
    border-radius: 5px;
    padding: 10px 13px;
    margin-top: 8px;
    cursor: pointer;
    text-decoration: none;
}

button:hover, .button:hover { background: #12558a; }
.danger { background: #b42318; }
.secondary { background: #52657a; }

.table-wrap { overflow-x: auto; }

table {
    width: 100%;
    border-collapse: collapse;
    background: white;
}

th, td {
    border: 1px solid #dce1e8;
    padding: 10px;
    text-align: left;
    vertical-align: top;
}

th { background: #e9eef5; }
td form { min-width: 130px; }

.photo-preview {
    display: none;
    max-width: 320px;
    max-height: 260px;
    margin-top: 12px;
    border-radius: 8px;
    object-fit: contain;
}

.photo-detail {
    max-width: 100%;
    max-height: 500px;
    border-radius: 8px;
    object-fit: contain;
}

.message {
    padding: 12px;
    margin-bottom: 12px;
    border-radius: 6px;
    background: #e8f2ff;
}

.error {
    background: #fff0f0;
    color: #b42318;
}

.login-card {
    max-width: 460px;
    margin: 35px auto;
}

@media (max-width: 600px) {
    nav a { margin: 6px; }
    main { padding: 0 10px; }
    .card { padding: 14px; }
}
</style>
"""

STAFF_NAV = """
<header>
    <h1>Facility Maintenance System</h1>
    <p>Digital Facility Damage Reporting &amp;
       Maintenance Tracking</p>
</header>
<nav>
    <a href="/">Report Damage</a>
    <a href="/admin/login">Admin Login</a>
</nav>
"""

ADMIN_NAV = """
<header>
    <h1>Facility Maintenance System</h1>
    <p>Maintenance Management Portal</p>
</header>
<nav>
    <a href="/dashboard">Dashboard</a>
    <a href="/complaints">View Complaints</a>
    <a href="/admin/logout">Logout</a>
</nav>
"""


# =====================================
# 5. ADMIN LOGIN AND LOGOUT
# =====================================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if "admin_username" in session:
        return redirect(url_for("dashboard"))

    error_message = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        stored_hash = ADMIN_ACCOUNTS.get(username)

        if (
            isinstance(stored_hash, str)
            and stored_hash
            and check_password_hash(stored_hash, password)
        ):
            session.clear()
            session["admin_username"] = username

            next_path = request.form.get("next", "")
            if valid_internal_path(next_path):
                return redirect(next_path)

            return redirect(url_for("dashboard"))

        error_message = "Invalid username or password."

    next_path = request.args.get("next", "")

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1">
        <title>Admin Login</title>
    """ + STYLE + """
    </head>
    <body>
    """ + STAFF_NAV + """
    <main>
        <div class="card login-card">
            <h2>Maintenance Admin Login</h2>
            <p class="muted">
                Authorised maintenance managers only.
            </p>

            {% if error_message %}
            <div class="message error">{{ error_message }}</div>
            {% endif %}

            <form method="POST">
                <input type="hidden" name="next" value="{{ next_path }}">

                <label>Username</label>
                <input type="text" name="username"
                       autocomplete="username" required>

                <label>Password</label>
                <input type="password" name="password"
                       autocomplete="current-password" required>

                <button type="submit">Login</button>
            </form>
        </div>
    </main>
    </body>
    </html>
    """

    response = app.make_response(render_template_string(
        html,
        error_message=error_message,
        next_path=next_path
    ))
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


# =====================================
# 6. STAFF DAMAGE REPORT FORM
# =====================================

@app.route("/", methods=["GET", "POST"])
def home():
    error_message = None
    success_message = None

    if request.method == "POST":
        reporter = request.form.get("reporter", "").strip()
        location = request.form.get("location", "").strip()
        damage = request.form.get("damage", "").strip()
        description = request.form.get("description", "").strip()
        priority = request.form.get("priority", "Medium")

        if not all([reporter, location, damage, description]):
            error_message = "Please complete all required fields."

        elif priority not in ALLOWED_PRIORITIES:
            error_message = "Invalid priority level."

        else:
            photo_path = None

            try:
                photo_path = save_uploaded_photo(
                    request.files.get("damage_photo")
                )
            except ValueError as exc:
                error_message = str(exc)

            if error_message is None:
                conn = get_connection()
                conn.execute("""
                    INSERT INTO complaints (
                        reporter, location, damage, description,
                        date_reported, status, priority, photo_path
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    reporter,
                    location,
                    damage,
                    description,
                    datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "Pending",
                    priority,
                    photo_path
                ))
                conn.commit()
                conn.close()

                success_message = (
                    "Your complaint was submitted successfully."
                )

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1">
        <title>Report Damage</title>
    """ + STYLE + """
    </head>
    <body>
    """ + STAFF_NAV + """
    <main>
        <div class="card">
            <h2>Report Facility Damage</h2>
            <p class="muted">
                Complete this form to report a facility problem.
            </p>

            {% if error_message %}
            <div class="message error">{{ error_message }}</div>
            {% endif %}

            {% if success_message %}
            <div class="message">{{ success_message }}</div>
            {% endif %}

            <form method="POST" enctype="multipart/form-data">
                <label>Reporter Name</label>
                <input type="text" name="reporter" required>

                <label>Building / Location</label>
                <input type="text" name="location"
                       placeholder="Example: Building A, Level 2"
                       required>

                <label>Type of Damage</label>
                <input type="text" name="damage"
                       placeholder="Example: Lamp Damage" required>

                <label>Description</label>
                <textarea name="description" rows="4" required></textarea>

                <label>Damage Photo (optional)</label>
                <input type="file" name="damage_photo"
                       accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
                       capture="environment"
                       onchange="previewDamagePhoto(event)">

                <p class="muted">
                    JPG, JPEG, PNG or WEBP; maximum 5 MB.
                </p>

                <img id="photoPreview" class="photo-preview"
                     alt="Damage photo preview">

                <label>Priority Level</label>
                <select name="priority" required>
                    <option value="Low">Low</option>
                    <option value="Medium" selected>Medium</option>
                    <option value="High">High</option>
                </select>

                <button type="submit">Submit Complaint</button>
            </form>
        </div>
    </main>

    <script>
    function previewDamagePhoto(event) {
        const file = event.target.files[0];
        const preview = document.getElementById("photoPreview");

        if (!file) {
            preview.style.display = "none";
            preview.removeAttribute("src");
            return;
        }

        const allowedTypes = [
            "image/jpeg", "image/png", "image/webp"
        ];

        if (!allowedTypes.includes(file.type)) {
            alert("Please select a JPG, PNG or WEBP image.");
            event.target.value = "";
            preview.style.display = "none";
            return;
        }

        if (file.size > 5 * 1024 * 1024) {
            alert("Image must be 5 MB or smaller.");
            event.target.value = "";
            preview.style.display = "none";
            return;
        }

        preview.src = URL.createObjectURL(file);
        preview.style.display = "block";
    }
    </script>
    </body>
    </html>
    """

    return render_template_string(
        html,
        error_message=error_message,
        success_message=success_message
    )


# =====================================
# 7. DASHBOARD
# =====================================

def get_dashboard_counts():
    conn = get_connection()
    counts = {}

    counts["total"] = conn.execute(
        "SELECT COUNT(*) FROM complaints"
    ).fetchone()[0]

    for status in ALLOWED_STATUSES:
        key = "status_" + status.lower().replace(" ", "_")
        counts[key] = conn.execute(
            "SELECT COUNT(*) FROM complaints WHERE status = ?",
            (status,)
        ).fetchone()[0]

    for priority in ALLOWED_PRIORITIES:
        counts["priority_" + priority.lower()] = conn.execute("""
            SELECT COUNT(*)
            FROM complaints
            WHERE COALESCE(priority, 'Medium') = ?
              AND status NOT IN ('Completed', 'Closed')
        """, (priority,)).fetchone()[0]

    conn.close()
    return counts


@app.route("/dashboard")
@admin_required
def dashboard():
    counts = get_dashboard_counts()

    cards = [
        ("Total Complaints", counts["total"],
         "/complaints", "All records"),
        ("Pending", counts["status_pending"],
         "/complaints?status=Pending", "Awaiting action"),
        ("In Progress", counts["status_in_progress"],
         "/complaints?status=In%20Progress", "Work underway"),
        ("Waiting Parts", counts["status_waiting_parts"],
         "/complaints?status=Waiting%20Parts", "Parts required"),
        ("Completed", counts["status_completed"],
         "/complaints?status=Completed", "Work completed"),
        ("Closed", counts["status_closed"],
         "/complaints?status=Closed", "Cases closed"),
        ("Open Low Priority", counts["priority_low"],
         "/complaints?priority=Low&open=1", "Low priority, open"),
        ("Open Medium Priority", counts["priority_medium"],
         "/complaints?priority=Medium&open=1", "Medium priority, open"),
        ("Open High Priority", counts["priority_high"],
         "/complaints?priority=High&open=1", "High priority, open")
    ]

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1">
        <title>Maintenance Dashboard</title>
    """ + STYLE + """
    </head>
    <body>
    """ + ADMIN_NAV + """
    <main>
        <h2>Maintenance Dashboard</h2>
        <p class="muted">
            Logged in as {{ username }}.
            Click a card to view related records.
        </p>

        <div class="dashboard">
        {% for title, number, link, hint in cards %}
            <a class="card stat" href="{{ link }}">
                <h3>{{ title }}</h3>
                <div class="number">{{ number }}</div>
                <div class="hint">{{ hint }} &rarr;</div>
            </a>
        {% endfor %}
        </div>
    </main>
    </body>
    </html>
    """

    return render_template_string(
        html,
        cards=cards,
        username=session["admin_username"]
    )


# =====================================
# 8. COMPLAINT LIST AND FILTERS
# =====================================

@app.route("/complaints")
@admin_required
def complaints():
    status_filter = request.args.get("status", "")
    priority_filter = request.args.get("priority", "")
    open_filter = request.args.get("open", "")

    if status_filter and status_filter not in ALLOWED_STATUSES:
        return "Invalid status filter.", 400

    if priority_filter and priority_filter not in ALLOWED_PRIORITIES:
        return "Invalid priority filter.", 400

    query = "SELECT * FROM complaints WHERE 1=1"
    params = []

    if status_filter:
        query += " AND status = ?"
        params.append(status_filter)

    if priority_filter:
        query += " AND COALESCE(priority, 'Medium') = ?"
        params.append(priority_filter)

    if open_filter == "1":
        query += " AND status NOT IN ('Completed', 'Closed')"

    query += " ORDER BY id DESC"

    conn = get_connection()
    records = conn.execute(query, params).fetchall()
    conn.close()

    filter_title = "All Complaint Records"

    if status_filter:
        filter_title = "Status: " + status_filter
    elif priority_filter:
        filter_title = "Priority: " + priority_filter + " (Open)"

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1">
        <title>Complaint Records</title>
    """ + STYLE + """
    </head>
    <body>
    """ + ADMIN_NAV + """
    <main>
        <h2>{{ filter_title }}</h2>
        <p>Logged in as {{ username }}.</p>
        <p><a href="/complaints">Show all records</a></p>

        {% if records %}
        <div class="table-wrap">
        <table>
            <tr>
                <th>ID</th><th>Reporter</th><th>Location</th>
                <th>Damage</th><th>Date</th><th>Photo</th>
                <th>Priority</th><th>Technician</th>
                <th>Status</th><th>Actions</th>
            </tr>

            {% for row in records %}
            <tr>
                <td>{{ row['id'] }}</td>
                <td>{{ row['reporter'] or '' }}</td>
                <td>{{ row['location'] or '' }}</td>
                <td>{{ row['damage'] or '' }}</td>
                <td>{{ row['date_reported'] or '' }}</td>
                <td>
                    {% if row['photo_path'] %}
                    <a href="{{ url_for('uploaded_photo',
                              filename=row['photo_path']) }}"
                       target="_blank" rel="noopener">View photo</a>
                    {% else %}
                    <span class="muted">No photo</span>
                    {% endif %}
                </td>
                <td>{{ row['priority'] or 'Medium' }}</td>
                <td>
                    <form method="POST"
                          action="/assign_technician/{{ row['id'] }}">
                        <select name="technician" required>
                            <option value="">Select technician</option>
                            {% for tech in technicians %}
                            <option value="{{ tech }}"
                            {% if row['technician'] == tech %}selected{% endif %}>
                                {{ tech }}
                            </option>
                            {% endfor %}
                        </select>
                        <button type="submit">Assign</button>
                    </form>
                </td>
                <td>
                    <form method="POST"
                          action="/update_status/{{ row['id'] }}">
                        <select name="status" required>
                            {% for s in statuses %}
                            <option value="{{ s }}"
                            {% if row['status'] == s %}selected{% endif %}>
                                {{ s }}
                            </option>
                            {% endfor %}
                        </select>
                        <button type="submit">Update</button>
                    </form>
                </td>
                <td>
                    <a class="button secondary"
                       href="/complaint/{{ row['id'] }}">Details</a>
                    <form method="POST"
                          action="/delete_complaint/{{ row['id'] }}"
                          onsubmit="return confirm(
                          'Delete this complaint permanently?'
                          );">
                        <button class="danger" type="submit">Delete</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
        </table>
        </div>
        {% else %}
        <div class="card">No complaints match this filter.</div>
        {% endif %}
    </main>
    </body>
    </html>
    """

    return render_template_string(
        html,
        records=records,
        technicians=TECHNICIANS,
        statuses=ALLOWED_STATUSES,
        filter_title=filter_title,
        username=session["admin_username"]
    )


# =====================================
# 9. COMPLAINT DETAILS
# =====================================

@app.route("/complaint/<int:complaint_id>")
@admin_required
def complaint_details(complaint_id):
    conn = get_connection()
    record = conn.execute(
        "SELECT * FROM complaints WHERE id = ?",
        (complaint_id,)
    ).fetchone()
    conn.close()

    if record is None:
        return "Complaint not found.", 404

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1">
        <title>Complaint Details</title>
    """ + STYLE + """
    </head>
    <body>
    """ + ADMIN_NAV + """
    <main>
        <div class="card">
            <h2>Complaint #{{ row['id'] }}</h2>
            <p><b>Reporter:</b> {{ row['reporter'] or '' }}</p>
            <p><b>Location:</b> {{ row['location'] or '' }}</p>
            <p><b>Damage:</b> {{ row['damage'] or '' }}</p>
            <p><b>Description:</b></p>
            <p>{{ row['description'] or '' }}</p>
            <p><b>Date Reported:</b>
                {{ row['date_reported'] or '' }}</p>
            <p><b>Priority:</b>
                {{ row['priority'] or 'Medium' }}</p>
            <p><b>Technician:</b>
                {{ row['technician'] or 'Not assigned' }}</p>
            <p><b>Status:</b> {{ row['status'] or 'Pending' }}</p>

            {% if row['photo_path'] %}
            <p><b>Damage Photo:</b></p>
            <a href="{{ url_for('uploaded_photo',
                      filename=row['photo_path']) }}"
               target="_blank" rel="noopener">
                <img class="photo-detail"
                     src="{{ url_for('uploaded_photo',
                              filename=row['photo_path']) }}"
                     alt="Reported damage">
            </a>
            {% else %}
            <p><b>Damage Photo:</b> No photo uploaded.</p>
            {% endif %}

            <p><a class="button" href="/complaints">
                Back to complaints</a></p>
        </div>
    </main>
    </body>
    </html>
    """

    return render_template_string(html, row=record)


# =====================================
# 10. SERVE PHOTOS TO AUTHENTICATED ADMINS
# =====================================

@app.route("/uploads/<path:filename>")
@admin_required
def uploaded_photo(filename):
    if os.path.basename(filename) != filename:
        abort(404)

    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename
    )


# =====================================
# 11. ASSIGN TECHNICIAN
# =====================================

@app.route(
    "/assign_technician/<int:complaint_id>",
    methods=["POST"]
)
@admin_required
def assign_technician(complaint_id):
    technician = request.form.get("technician", "")

    if technician not in TECHNICIANS:
        return "Invalid technician.", 400

    conn = get_connection()
    cursor = conn.execute(
        "UPDATE complaints SET technician = ? WHERE id = ?",
        (technician, complaint_id)
    )
    conn.commit()
    found = cursor.rowcount
    conn.close()

    if not found:
        return "Complaint not found.", 404

    return redirect(url_for("complaints"))


# =====================================
# 12. UPDATE STATUS
# =====================================

@app.route(
    "/update_status/<int:complaint_id>",
    methods=["POST"]
)
@admin_required
def update_status(complaint_id):
    status = request.form.get("status", "")

    if status not in ALLOWED_STATUSES:
        return "Invalid status.", 400

    conn = get_connection()
    cursor = conn.execute(
        "UPDATE complaints SET status = ? WHERE id = ?",
        (status, complaint_id)
    )
    conn.commit()
    found = cursor.rowcount
    conn.close()

    if not found:
        return "Complaint not found.", 404

    return redirect(url_for("complaints"))


# =====================================
# 13. DELETE COMPLAINT
# =====================================

@app.route(
    "/delete_complaint/<int:complaint_id>",
    methods=["POST"]
)
@admin_required
def delete_complaint(complaint_id):
    conn = get_connection()
    record = conn.execute(
        "SELECT photo_path FROM complaints WHERE id = ?",
        (complaint_id,)
    ).fetchone()

    if record is None:
        conn.close()
        return "Complaint not found.", 404

    photo_path = record["photo_path"]

    conn.execute(
        "DELETE FROM complaints WHERE id = ?",
        (complaint_id,)
    )
    conn.commit()
    conn.close()

    if photo_path:
        filename = os.path.basename(photo_path)
        image_path = os.path.join(UPLOAD_FOLDER, filename)

        if os.path.isfile(image_path):
            os.remove(image_path)

    return redirect(url_for("complaints"))


# =====================================
# 14. ERROR HANDLERS
# =====================================

@app.errorhandler(413)
def file_too_large(error):
    return "Image too large. Maximum upload size is 5 MB.", 413


# =====================================
# 15. INITIALIZE DATABASE
# =====================================

create_database()

if __name__ == "__main__":
    app.run(debug=False, port=5000)
