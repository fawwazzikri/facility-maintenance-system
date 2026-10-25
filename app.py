from flask import (
    Flask, render_template_string, request, redirect,
    url_for, send_from_directory, abort, session
)
import os
import uuid
import json
from datetime import datetime
from functools import wraps
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
import psycopg
from psycopg.rows import dict_row

app = Flask(__name__)

# Environment variables: Render
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if os.environ.get("RENDER"):
        raise RuntimeError("SECRET_KEY is missing.")
    SECRET_KEY = os.urandom(32).hex()

app.secret_key = SECRET_KEY
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("RENDER"))
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing.")

try:
    ADMIN_ACCOUNTS = json.loads(
        os.environ.get("ADMIN_ACCOUNTS", "{}")
    )
except json.JSONDecodeError:
    raise RuntimeError("ADMIN_ACCOUNTS must be valid JSON.")

if not isinstance(ADMIN_ACCOUNTS, dict) or not ADMIN_ACCOUNTS:
    raise RuntimeError("ADMIN_ACCOUNTS is empty or invalid.")

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
# 1. DATABASE - NEON POSTGRESQL
# =====================================

def get_connection():
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        sslmode="require"
    )


def create_database():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS complaints (
                id BIGSERIAL PRIMARY KEY,
                reporter TEXT,
                location TEXT,
                damage TEXT,
                description TEXT,
                date_reported TEXT,
                status TEXT DEFAULT 'Pending',
                technician TEXT,
                priority TEXT DEFAULT 'Medium',
                photo_path TEXT
            )
        """)

        conn.execute("""
            ALTER TABLE complaints
            ADD COLUMN IF NOT EXISTS technician TEXT
        """)
        conn.execute("""
            ALTER TABLE complaints
            ADD COLUMN IF NOT EXISTS priority TEXT DEFAULT 'Medium'
        """)
        conn.execute("""
            ALTER TABLE complaints
            ADD COLUMN IF NOT EXISTS photo_path TEXT
        """)


def admin_required(view_function):
    @wraps(view_function)
    def wrapped(*args, **kwargs):
        if "admin_username" not in session:
            return redirect(
                url_for("admin_login", next=request.path)
            )
        return view_function(*args, **kwargs)
    return wrapped


def valid_internal_path(path):
    return (
        isinstance(path, str)
        and path.startswith("/")
        and not path.startswith("//")
        and "\\" not in path
    )


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
        raise ValueError(
            "Use JPG, JPEG, PNG or WEBP images only."
        )

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
# 2. DASHBOARD COUNTS
# =====================================


def get_dashboard_counts():
    counts = {}

    with get_connection() as conn:
        # Total complaints exclude Closed cases
        row = conn.execute("""
            SELECT COUNT(*) AS count
            FROM complaints
            WHERE status IS DISTINCT FROM %s
        """, ("Closed",)).fetchone()

        counts["total"] = row["count"]

        # Count complaints by status
        for status in ALLOWED_STATUSES:
            key = "status_" + status.lower().replace(" ", "_")

            row = conn.execute("""
                SELECT COUNT(*) AS count
                FROM complaints
                WHERE status = %s
            """, (status,)).fetchone()

            counts[key] = row["count"]

        # Count open complaints by priority
        for priority in ALLOWED_PRIORITIES:
            key = "priority_" + priority.lower()

            row = conn.execute("""
                SELECT COUNT(*) AS count
                FROM complaints
                WHERE COALESCE(priority, 'Medium') = %s
                  AND status NOT IN ('Completed', 'Closed')
            """, (priority,)).fetchone()

            counts[key] = row["count"]

    return counts



# =====================================
# 3. WEBSITE STYLE
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
    padding: 15px;
    text-align: center;
}

nav a {
    color: white;
    text-decoration: none;
    margin: 0 12px;
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
    transition: transform .15s, box-shadow .15s;
}

.stat:hover {
    transform: translateY(-3px);
    box-shadow: 0 5px 14px #00000020;
}

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
.danger:hover { background: #8f1d14; }
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

@media (max-width: 600px) {
    nav a {
        display: inline-block;
        margin: 6px;
    }
}
</style>
"""

NAV = """
<header>
    <h1>Facility Maintenance System</h1>
    <p>Digital Facility Damage Reporting &amp; Maintenance Tracking</p>
</header>

<nav>
    <a href="/">Report Damage</a>
    <a href="/dashboard">Dashboard</a>
    <a href="/complaints">View Complaints</a>
    <a href="/admin/logout">Log out</a>
</nav>
"""
# =====================================
# 4. ADMIN LOGIN / LOGOUT
# =====================================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error_message = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        password_hash = ADMIN_ACCOUNTS.get(username)

        if password_hash and check_password_hash(
            password_hash, password
        ):
            session.clear()
            session["admin_username"] = username

            next_path = request.form.get("next", "")
            if valid_internal_path(next_path):
                return redirect(next_path)

            return redirect(url_for("dashboard"))

        error_message = "Username or password is incorrect."

    next_path = request.args.get("next", "")

    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Admin Login</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        """ + STYLE + """
    </head>
    <body>
        <header>
            <h1>GES Maintenance Team</h1>
            <p>Administrator Login</p>
        </header>
        <main>
            <div class="card" style="max-width:500px;margin:auto;">
                <h2>Admin Login</h2>

                {% if error_message %}
                    <p style="color:#b42318;">{{ error_message }}</p>
                {% endif %}

                <form method="POST">
                    <input type="hidden" name="next" value="{{ next_path }}">

                    <label>Username</label>
                    <input name="username" autocomplete="username" required>

                    <label>Password</label>
                    <input type="password" name="password"
                           autocomplete="current-password" required>

                    <button type="submit">Log in</button>
                </form>

                <p><a href="/">Back to Report Damage</a></p>
            </div>
        </main>
    </body>
    </html>
    """, error_message=error_message, next_path=next_path)


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


# =====================================
# 5. PUBLIC REPORT DAMAGE FORM
# =====================================

@app.route("/", methods=["GET", "POST"])
def home():
    error_message = None
    success_message = (
        "Your complaint was submitted successfully."
        if request.args.get("submitted") == "1"
        else None
    )

    if request.method == "POST":
        reporter = request.form.get("reporter", "").strip()
        location = request.form.get("location", "").strip()
        damage = request.form.get("damage", "").strip()
        description = request.form.get("description", "").strip()
        priority = request.form.get("priority", "Medium")
        photo = request.files.get("photo")
        photo_filename = None

        if not reporter or not location or not damage or not description:
            error_message = "Please complete all required fields."

        elif priority not in ALLOWED_PRIORITIES:
            error_message = "Invalid priority selected."

        else:
            try:
                if photo and photo.filename:
                    photo_filename = save_uploaded_photo(photo)

                reported_at = datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                with get_connection() as conn:
                    conn.execute("""
                        INSERT INTO complaints
                        (reporter, location, damage, description,
                         date_reported, status, technician, priority,
                         photo_path)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        reporter, location, damage, description,
                        reported_at, "Pending", None, priority,
                        photo_filename
                    ))

                return redirect(url_for("home", submitted="1"))

            except (ValueError, psycopg.Error) as error:
                if photo_filename:
                    try:
                        os.remove(
                            os.path.join(UPLOAD_FOLDER, photo_filename)
                        )
                    except OSError:
                        pass

                app.logger.exception("Could not save complaint")
                error_message = (
                    str(error) if isinstance(error, ValueError)
                    else "Unable to save the complaint. Please try again."
                )

    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Report Damage</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        """ + STYLE + """
    </head>
    <body>
        <header>
            <h1>Report Facility Damage</h1>
            <p>GES Maintenance Team</p>
        </header>

        <main>
            <div class="card">
                <h2>Submit a Damage Report</h2>
                <p>Complete this form to report a facility problem.</p>

                {% if error_message %}
                    <p style="color:#b42318;">{{ error_message }}</p>
                {% endif %}

                {% if success_message %}
                    <p style="color:#067647;font-weight:bold;">
                        {{ success_message }}
                    </p>
                {% endif %}

                <form method="POST" enctype="multipart/form-data">
                    <label>Reporter Name *</label>
                    <input name="reporter" required>

                    <label>Location *</label>
                    <input name="location" required
                           placeholder="Building, floor or room">

                    <label>Type of Damage *</label>
                    <input name="damage" required
                           placeholder="e.g. Air conditioning, lighting">

                    <label>Description *</label>
                    <textarea name="description" rows="4" required></textarea>

                    <label>Priority</label>
                    <select name="priority">
                        <option>Low</option>
                        <option selected>Medium</option>
                        <option>High</option>
                    </select>

                    <label>Photo (optional, maximum 5 MB)</label>
                    <input type="file" name="photo"
                           accept=".jpg,.jpeg,.png,.webp">

                    <button type="submit">Submit Complaint</button>
                </form>
            </div>

            <p style="text-align:center;">
                <a href="/admin/login">Maintenance Team Login</a>
            </p>
        </main>
    </body>
    </html>
    """, error_message=error_message,
         success_message=success_message)


# =====================================
# 6. ADMIN DASHBOARD
# =====================================

@app.route("/dashboard")
@admin_required
def dashboard():
    counts = get_dashboard_counts()

    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Maintenance Dashboard</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        """ + STYLE + """
    </head>
    <body>
        """ + NAV + """
        <main>
            <h1>Maintenance Dashboard</h1>
            <p>
                Logged in as {{ session.get("admin_username") }}.
                Click a card to view related records.
            </p>

            <div class="dashboard">
                <a class="card stat" href="/complaints">
                    <h3>Total Complaints</h3>
                    <div class="number">{{ counts.total }}</div>
                    <div class="hint">All records →</div>
                </a>

                <a class="card stat" href="/complaints?status=Pending">
                    <h3>Pending</h3>
                    <div class="number">{{ counts.status_pending }}</div>
                    <div class="hint">Awaiting action →</div>
                </a>

                <a class="card stat" href="/complaints?status=In%20Progress">
                    <h3>In Progress</h3>
                    <div class="number">{{ counts.status_in_progress }}</div>
                    <div class="hint">Work underway →</div>
                </a>

                <a class="card stat" href="/complaints?status=Waiting%20Parts">
                    <h3>Waiting Parts</h3>
                    <div class="number">{{ counts.status_waiting_parts }}</div>
                    <div class="hint">Parts required →</div>
                </a>

                <a class="card stat" href="/complaints?status=Completed">
                    <h3>Completed</h3>
                    <div class="number">{{ counts.status_completed }}</div>
                    <div class="hint">Work completed →</div>
                </a>

                <a class="card stat" href="/complaints?status=Closed">
                    <h3>Closed</h3>
                    <div class="number">{{ counts.status_closed }}</div>
                    <div class="hint">Cases closed →</div>
                </a>

                <a class="card stat" href="/complaints?priority=Low">
                    <h3>Open Low Priority</h3>
                    <div class="number">{{ counts.priority_low }}</div>
                </a>

                <a class="card stat" href="/complaints?priority=Medium">
                    <h3>Open Medium Priority</h3>
                    <div class="number">{{ counts.priority_medium }}</div>
                </a>

                <a class="card stat" href="/complaints?priority=High">
                    <h3>Open High Priority</h3>
                    <div class="number">{{ counts.priority_high }}</div>
                </a>
            </div>
        </main>
    </body>
    </html>
    """, counts=counts)
    
# =====================================
# 7. COMPLAINT LIST AND FILTERS
# =====================================

@app.route("/complaints")
@admin_required
def complaints():
    status_filter = request.args.get("status", "")
    priority_filter = request.args.get("priority", "")

    if status_filter and status_filter not in ALLOWED_STATUSES:
        return "Invalid status filter.", 400

    if priority_filter and priority_filter not in ALLOWED_PRIORITIES:
        return "Invalid priority filter.", 400

    query = "SELECT * FROM complaints WHERE 1=1"
    params = []

    if status_filter:
        query += " AND status = %s"
        params.append(status_filter)

    if priority_filter:
        query += " AND COALESCE(priority, 'Medium') = %s"
        params.append(priority_filter)

    query += " ORDER BY id DESC"

    with get_connection() as conn:
        records = conn.execute(query, params).fetchall()

    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Complaint Records</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        """ + STYLE + """
    </head>
    <body>
        """ + NAV + """
        <main>
            <h2>Complaint Records</h2>
            <p>{{ records|length }} record(s) found.</p>

            <p><a href="/complaints">Show all records</a></p>

            {% if records %}
            <div class="table-wrap">
            <table>
                <tr>
                    <th>ID</th>
                    <th>Reporter</th>
                    <th>Location</th>
                    <th>Damage</th>
                    <th>Date</th>
                    <th>Priority</th>
                    <th>Technician</th>
                    <th>Status</th>
                    <th>Actions</th>
                </tr>

                {% for row in records %}
                <tr>
                    <td>{{ row.id }}</td>
                    <td>{{ row.reporter or "" }}</td>
                    <td>{{ row.location or "" }}</td>
                    <td>{{ row.damage or "" }}</td>
                    <td>{{ row.date_reported or "" }}</td>
                    <td>{{ row.priority or "Medium" }}</td>

                    <td>
                        <form method="POST"
                              action="/assign_technician/{{ row.id }}">
                            <select name="technician" required>
                                <option value="">Select technician</option>
                                {% for tech in technicians %}
                                <option value="{{ tech }}"
                                {% if row.technician == tech %}selected{% endif %}>
                                    {{ tech }}
                                </option>
                                {% endfor %}
                            </select>
                            <button type="submit">Assign</button>
                        </form>
                    </td>

                    <td>
                        <form method="POST"
                              action="/update_status/{{ row.id }}">
                            <select name="status" required>
                                {% for s in statuses %}
                                <option value="{{ s }}"
                                {% if row.status == s %}selected{% endif %}>
                                    {{ s }}
                                </option>
                                {% endfor %}
                            </select>
                            <button type="submit">Update</button>
                        </form>
                    </td>

                    <td>
                        <a class="button"
                           href="/complaint/{{ row.id }}">Details</a>

                        <form method="POST"
                              action="/delete_complaint/{{ row.id }}"
                              onsubmit="return confirm(
                              'Delete this complaint permanently?'
                              );">
                            <button class="danger" type="submit">
                                Delete
                            </button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
            </table>
            </div>
            {% else %}
            <div class="card">No complaints found.</div>
            {% endif %}
        </main>
    </body>
    </html>
    """,
    records=records,
    technicians=TECHNICIANS,
    statuses=ALLOWED_STATUSES)


# =====================================
# 8. COMPLAINT DETAILS
# =====================================

@app.route("/complaint/<int:complaint_id>")
@admin_required
def complaint_details(complaint_id):
    with get_connection() as conn:
        record = conn.execute(
            "SELECT * FROM complaints WHERE id = %s",
            (complaint_id,)
        ).fetchone()

    if record is None:
        return "Complaint not found.", 404

    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Complaint Details</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        """ + STYLE + """
    </head>
    <body>
        """ + NAV + """
        <main>
            <div class="card">
                <h2>Complaint #{{ row.id }}</h2>

                <p><b>Reporter:</b> {{ row.reporter or "" }}</p>
                <p><b>Location:</b> {{ row.location or "" }}</p>
                <p><b>Damage:</b> {{ row.damage or "" }}</p>
                <p><b>Description:</b></p>
                <p>{{ row.description or "" }}</p>
                <p><b>Date reported:</b> {{ row.date_reported or "" }}</p>
                <p><b>Priority:</b> {{ row.priority or "Medium" }}</p>
                <p><b>Technician:</b>
                    {{ row.technician or "Not assigned" }}
                </p>
                <p><b>Status:</b> {{ row.status or "Pending" }}</p>

                {% if row.photo_path %}
                    <p><b>Damage Photo:</b></p>
                    <img class="photo-detail"
                         src="{{ url_for('uploaded_photo',
                                          filename=row.photo_path) }}"
                         alt="Reported damage">
                {% else %}
                    <p>No photo uploaded.</p>
                {% endif %}

                <p><a class="button" href="/complaints">
                    Back to complaints
                </a></p>
            </div>
        </main>
    </body>
    </html>
    """, row=record)


# =====================================
# 9. SERVE UPLOADED PHOTOS
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
# 10. ASSIGN TECHNICIAN
# =====================================

@app.route("/assign_technician/<int:complaint_id>",
           methods=["POST"])
@admin_required
def assign_technician(complaint_id):
    technician = request.form.get("technician", "")

    if technician not in TECHNICIANS:
        return "Invalid technician.", 400

    with get_connection() as conn:
        result = conn.execute(
            "UPDATE complaints SET technician = %s WHERE id = %s",
            (technician, complaint_id)
        )

        found = result.rowcount

    if not found:
        return "Complaint not found.", 404

    return redirect(request.referrer or url_for("complaints"))


# =====================================
# 11. UPDATE STATUS
# =====================================

@app.route("/update_status/<int:complaint_id>",
           methods=["POST"])
@admin_required
def update_status(complaint_id):
    status = request.form.get("status", "")

    if status not in ALLOWED_STATUSES:
        return "Invalid status.", 400

    with get_connection() as conn:
        result = conn.execute(
            "UPDATE complaints SET status = %s WHERE id = %s",
            (status, complaint_id)
        )

        found = result.rowcount

    if not found:
        return "Complaint not found.", 404

    return redirect(request.referrer or url_for("complaints"))


# =====================================
# 12. DELETE COMPLAINT
# =====================================

@app.route("/delete_complaint/<int:complaint_id>",
           methods=["POST"])
@admin_required
def delete_complaint(complaint_id):
    with get_connection() as conn:
        record = conn.execute(
            "SELECT photo_path FROM complaints WHERE id = %s",
            (complaint_id,)
        ).fetchone()

        if record is None:
            return "Complaint not found.", 404

        photo_path = record["photo_path"]

        conn.execute(
            "DELETE FROM complaints WHERE id = %s",
            (complaint_id,)
        )

    if photo_path:
        image_path = os.path.join(
            UPLOAD_FOLDER,
            os.path.basename(photo_path)
        )
        if os.path.isfile(image_path):
            os.remove(image_path)

    return redirect(url_for("complaints"))


# =====================================
# 13. START APPLICATION
# =====================================

# Create the database table when Gunicorn imports this application.
create_database()

if __name__ == "__main__":
    app.run(debug=False, port=5000)
