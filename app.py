
from flask import (
    Flask, render_template_string, request, redirect,
    url_for, send_from_directory, abort
)
import sqlite3
import os
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__)

# =====================================
# 1. APPLICATION CONFIGURATION
# =====================================

DATABASE = os.path.join(app.root_path, "maintenance.db")
UPLOAD_FOLDER = os.path.join(app.root_path, "uploads")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

ALLOWED_STATUSES = [
    "Pending",
    "In Progress",
    "Waiting Parts",
    "Completed",
    "Closed"
]

ALLOWED_PRIORITIES = ["Low", "Medium", "High"]

TECHNICIANS = [
    "Technician A",
    "Technician B",
    "Technician C"
]

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


# =====================================
# 2. DATABASE
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

    columns = [
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(complaints)"
        ).fetchall()
    ]

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
        raise ValueError(
            "Use JPG, JPEG, PNG or WEBP images only."
        )

    data = photo.stream.read(5 * 1024 * 1024 + 1)

    if len(data) > 5 * 1024 * 1024:
        raise ValueError(
            "Image must be 5 MB or smaller."
        )

    extension = safe_name.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{extension}"
    destination = os.path.join(UPLOAD_FOLDER, filename)

    with open(destination, "wb") as image_file:
        image_file.write(data)

    return filename


# =====================================
# 3. WEBSITE DESIGN
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
    margin: 6px 12px;
    font-weight: bold;
    display: inline-block;
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
    grid-template-columns: repeat(
        auto-fit, minmax(185px, 1fr)
    );
    gap: 16px;
    margin: 20px 0;
}

.stat {
    display: block;
    color: #263244;
    text-decoration: none;
    transition: transform .15s;
}

.stat:hover {
    transform: translateY(-3px);
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

button:hover, .button:hover {
    background: #12558a;
}

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

.error {
    background: #fff0f0;
    color: #b42318;
    padding: 12px;
    border-radius: 6px;
}

@media (max-width: 600px) {
    nav a { margin: 6px; }
    main { padding: 0 10px; }
    .card { padding: 14px; }
}
</style>
"""

NAV = """
<header>
    <h1>Facility Maintenance System</h1>
    <p>Digital Facility Damage Reporting &amp;
       Maintenance Tracking</p>
</header>
<nav>
    <a href="/">Report Damage</a>
    <a href="/dashboard">Dashboard</a>
    <a href="/complaints">View Complaints</a>
</nav>
"""


# =====================================
# 4. REPORT DAMAGE
# =====================================

@app.route("/", methods=["GET", "POST"])
def home():
    error_message = None

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

                return redirect(url_for("complaints"))

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
    """ + NAV + """
    <main>
        <div class="card">
            <h2>Report Facility Damage</h2>
            <p class="muted">
                Complete the form to report a facility problem.
            </p>

            {% if error_message %}
            <div class="error">{{ error_message }}</div>
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
                <textarea name="description"
                          rows="4" required></textarea>

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
        html, error_message=error_message
    )


# =====================================
# 5. DASHBOARD
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
    """ + NAV + """
    <main>
        <h2>Maintenance Dashboard</h2>
        <p class="muted">
            Click a card to view related complaint records.
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

        <div class="card">
            <h3>Dashboard Information</h3>
            <p>
                Open priority counts exclude Completed and Closed
                complaints.
            </p>
            <a class="button" href="/complaints">
                Manage Complaints
            </a>
        </div>
    </main>
    </body>
    </html>
    """

    return render_template_string(html, cards=cards)


# =====================================
# 6. COMPLAINT LIST AND FILTERS
# =====================================

@app.route("/complaints")
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
    """ + NAV + """
    <main>
        <h2>{{ filter_title }}</h2>
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
                <th>Photo</th>
                <th>Priority</th>
                <th>Technician</th>
                <th>Status</th>
                <th>Actions</th>
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
        filter_title=filter_title
    )


# =====================================
# 7. COMPLAINT DETAILS
# =====================================

@app.route("/complaint/<int:complaint_id>")
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
    """ + NAV + """
    <main>
        <div class="card">
            <h2>Complaint #{{ row['id'] }}</h2>
            <p><b>Reporter:</b> {{ row['reporter'] or '' }}</p>
            <p><b>Location:</b> {{ row['location'] or '' }}</p>
            <p><b>Damage:</b> {{ row['damage'] or '' }}</p>
            <p><b>Description:</b></p>
            <p>{{ row['description'] or '' }}</p>
            <p><b>Date Reported:</b>
                {{ row['date_reported'] or '' }}
            </p>
            <p><b>Priority:</b>
                {{ row['priority'] or 'Medium' }}
            </p>
            <p><b>Technician:</b>
                {{ row['technician'] or 'Not assigned' }}
            </p>
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

            <p>
                <a class="button" href="/complaints">
                    Back to complaints
                </a>
            </p>
        </div>
    </main>
    </body>
    </html>
    """

    return render_template_string(html, row=record)


# =====================================
# 8. SERVE UPLOADED PHOTOS
# =====================================

@app.route("/uploads/<path:filename>")
def uploaded_photo(filename):
    if os.path.basename(filename) != filename:
        abort(404)

    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename
    )


# =====================================
# 9. ASSIGN TECHNICIAN
# =====================================

@app.route(
    "/assign_technician/<int:complaint_id>",
    methods=["POST"]
)
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

    return redirect(request.referrer or url_for("complaints"))


# =====================================
# 10. UPDATE STATUS
# =====================================

@app.route(
    "/update_status/<int:complaint_id>",
    methods=["POST"]
)
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

    return redirect(request.referrer or url_for("complaints"))


# =====================================
# 11. DELETE COMPLAINT
# =====================================

@app.route(
    "/delete_complaint/<int:complaint_id>",
    methods=["POST"]
)
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

    return redirect(request.referrer or url_for("complaints"))


# =====================================
# 12. INITIALIZE DATABASE AND START
# =====================================

# Runs when Gunicorn imports this module on Render.
create_database()

if __name__ == "__main__":
    app.run(debug=False, port=5000)
