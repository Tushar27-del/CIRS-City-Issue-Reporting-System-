
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DB_FILE = 'city_issues.db'

# ----------------- DB Connection -----------------
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# ----------------- Initialize DB -----------------
def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'citizen',
        admin_department TEXT,
        state TEXT,
        city TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS complaints (
        complaint_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        title TEXT,
        description TEXT,
        category TEXT,
        department TEXT,
        status TEXT DEFAULT 'Pending',
        image TEXT,
        latitude TEXT,
        longitude TEXT,
        address TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS feedback (
        feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
        complaint_id INTEGER,
        user_id INTEGER,
        feedback TEXT,
        rating INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(complaint_id) REFERENCES complaints(complaint_id),
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )''')
    conn.commit()
    conn.close()

init_db()

# ----------------- EXIF GPS Function -----------------
def get_exif_location(image_path):
    try:
        img = Image.open(image_path)
        exif_data = img._getexif()
        if not exif_data:
            return None, None
        gps_info = {}
        for tag, value in exif_data.items():
            decoded = TAGS.get(tag, tag)
            if decoded == "GPSInfo":
                for t in value:
                    sub_decoded = GPSTAGS.get(t, t)
                    gps_info[sub_decoded] = value[t]
        if not gps_info:
            return None, None

        def convert_to_degrees(value):
            d = value[0][0] / value[0][1]
            m = value[1][0] / value[1][1]
            s = value[2][0] / value[2][1]
            return d + (m / 60.0) + (s / 3600.0)

        lat = convert_to_degrees(gps_info["GPSLatitude"])
        if gps_info["GPSLatitudeRef"] != "N":
            lat = -lat
        lon = convert_to_degrees(gps_info["GPSLongitude"])
        if gps_info["GPSLongitudeRef"] != "E":
            lon = -lon
        return lat, lon
    except Exception as e:
        print("EXIF extraction error:", e)
        return None, None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ----------------- Routes -----------------
@app.route('/')
def home():
    return render_template('base.html')
@app.context_processor
def inject_dashboard_stats():
    conn = get_db_connection()
    c = conn.cursor()

    # Total users
    c.execute("SELECT COUNT(*) as total_users FROM users")
    total_users = c.fetchone()['total_users']

    # Total complaints
    c.execute("SELECT COUNT(*) as total_complaints FROM complaints")
    total_complaints = c.fetchone()['total_complaints']

    # Resolution rate
    c.execute("SELECT COUNT(*) as resolved_count FROM complaints WHERE status='Resolved'")
    resolved_count = c.fetchone()['resolved_count']

    resolution_rate = 0
    if total_complaints > 0:
        resolution_rate = round((resolved_count / total_complaints) * 100, 2)

    conn.close()

    return dict(
        total_users=total_users,
        total_complaints=total_complaints,
        resolution_rate=resolution_rate
    )
# ----------------- Register -----------------
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method=='POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        password = generate_password_hash(request.form['password'])
        role = request.form.get('role','citizen')
        admin_department = request.form.get('admin_department') if role=='admin' else None
        conn = get_db_connection()
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (name,email,password,role,admin_department) VALUES (?,?,?,?,?)",
                      (name,email,password,role,admin_department))
            conn.commit()
            flash('User registered successfully','success')
        except sqlite3.IntegrityError:
            flash('Email already exists','danger')
        conn.close()
        return redirect(url_for('login'))
    return render_template('register.html')

# ----------------- Login -----------------
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email=? AND role='citizen'", (email,))
        user = c.fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['user_id']
            session['role'] = 'citizen'
            session['name'] = user['name']
            flash('Logged in successfully','success')
            return redirect(url_for('dashboard_user'))
        else:
            flash('Invalid credentials','danger')
    return render_template('login.html')

# ----------------- Admin Login -----------------
@app.route('/login_admin', methods=['GET','POST'])
def login_admin():
    if request.method=='POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email=? AND role='admin'", (email,))
        admin = c.fetchone()
        conn.close()
        if admin and check_password_hash(admin['password'], password):
            session['user_id'] = admin['user_id']
            session['role'] = 'admin'
            session['name'] = admin['name']
            session['admin_department'] = admin['admin_department']
            flash('Admin logged in successfully','success')
            return redirect(url_for('dashboard_admin'))
        else:
            flash('Invalid admin credentials','danger')
    return render_template('login_admin.html')

# ----------------- User Dashboard -----------------
@app.route('/dashboard_user')
def dashboard_user():
    if 'user_id' not in session or session['role'] != 'citizen':
        return redirect(url_for('login'))
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM complaints WHERE user_id=?", (session['user_id'],))
    complaints = c.fetchall()
    conn.close()
    return render_template('dashboard_user.html', complaints=complaints)
# ----------------- Profile Route -----------------
@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        flash("Please login first", "warning")
        return redirect(url_for('login'))

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (session['user_id'],))
    user = c.fetchone()

    if request.method == "POST":
        # Get form data
        name = request.form['name']
        email = request.form['email']
        age = request.form.get('age')
        address = request.form.get('address')
        latitude = request.form.get('latitude')
        longitude = request.form.get('longitude')

        # Handle photo upload
        photo_file = request.files.get('photo')
        photo_filename = user['photo']
        if photo_file and allowed_file(photo_file.filename):
            filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{photo_file.filename}")
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            photo_file.save(save_path)
            photo_filename = filename

        # Update user in DB
        c.execute("""UPDATE users SET name=?, email=?, age=?, address=?, latitude=?, longitude=?, photo=? 
                     WHERE user_id=?""",
                  (name, email, age, address, latitude, longitude, photo_filename, session['user_id']))
        conn.commit()
        conn.close()
        flash("✅ Profile updated successfully", "success")
        return redirect(url_for('profile'))

    conn.close()
    return render_template('profile.html', user=user)


# ----------------- Admin Dashboard -----------------


@app.route('/dashboard_admin', methods=['GET'])
def dashboard_admin():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login_admin'))

    conn = get_db_connection()
    c = conn.cursor()

    # Get admin info
    c.execute("SELECT * FROM users WHERE user_id=?", (session['user_id'],))
    admin = c.fetchone()
    dept = admin['admin_department'] if admin else 'General Admin'

    # Base query: join complaints with citizen name
    query = """
        SELECT complaints.*, users.name AS citizen_name
        FROM complaints
        JOIN users ON complaints.user_id = users.user_id
        WHERE 1=1
    """
    params = []

    # Restrict complaints for non-General Admins
    if dept != 'General Admin':
        query += " AND department=?"
        params.append(dept)

    # Get filters from GET request
    filter_department = request.args.get('department')
    filter_category = request.args.get('category')
    filter_status = request.args.get('status')

    # Only General Admin can filter by department
    if filter_department and dept == 'General Admin':
        query += " AND department=?"
        params.append(filter_department)
    if filter_category:
        query += " AND category=?"
        params.append(filter_category)
    if filter_status:
        query += " AND status=?"
        params.append(filter_status)

    query += " ORDER BY complaints.created_at DESC"
    c.execute(query, params)
    complaints = c.fetchall()

    # Departments dropdown
    if dept != 'General Admin':
        c.execute("SELECT DISTINCT department FROM complaints WHERE department=?", (dept,))
    else:
        c.execute("SELECT DISTINCT department FROM complaints")
    departments = [row['department'] for row in c.fetchall()]

    # Categories dropdown
    if dept != 'General Admin':
        c.execute("SELECT DISTINCT category FROM complaints WHERE department=?", (dept,))
    else:
        c.execute("SELECT DISTINCT category FROM complaints")
    categories = [row['category'] for row in c.fetchall()]

    conn.close()

    return render_template(
        'dashboard_admin.html',
        complaints=complaints,
        admin=admin,
        departments=departments,
        categories=categories,
        filter_department=filter_department,
        filter_category=filter_category,
        filter_status=filter_status
    )



# ----------------- Update Complaint Status -----------------
@app.route('/update_status/<int:complaint_id>', methods=['POST'])
def update_status(complaint_id):
    if 'user_id' not in session or session['role'] != 'admin':
        flash("Unauthorized", "danger")
        return redirect(url_for('login_admin'))

    new_status = request.form.get('status')
    if new_status not in ['Pending', 'In Progress', 'Resolved']:
        flash("Invalid status", "danger")
        return redirect(url_for('dashboard_admin'))

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE complaints SET status=? WHERE complaint_id=?", (new_status, complaint_id))
    conn.commit()
    conn.close()

    flash(f"Complaint status updated to {new_status}", "success")
    return redirect(url_for('dashboard_admin'))
# ----------------- Delete Complaint (Admin) -----------------
@app.route('/admin/delete/<int:complaint_id>', methods=['POST'])
def admin_delete_complaint(complaint_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash("Unauthorized access", "danger")
        return redirect(url_for('login'))

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT status FROM complaints WHERE complaint_id=?", (complaint_id,))
    complaint = c.fetchone()
    if complaint and complaint['status'] == 'Resolved':
        c.execute("DELETE FROM complaints WHERE complaint_id=?", (complaint_id,))
        conn.commit()
        flash("Complaint deleted successfully", "success")
    else:
        flash("Cannot delete complaint unless it is resolved", "warning")
    conn.close()
    return redirect(url_for('dashboard_admin'))


# Admin feedback page
@app.route('/admin_feedback')
def admin_feedback():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login_admin'))

    complaint_id = request.args.get('complaint_id')
    conn = get_db_connection()
    c = conn.cursor()

    # Get admin info and department
    c.execute("SELECT * FROM users WHERE user_id=?", (session['user_id'],))
    admin = c.fetchone()
    dept = admin['admin_department'] if admin else 'General Admin'

    # Base query to fetch feedback with citizen name and rating
    base_query = """
        SELECT f.feedback AS comments,
               f.rating,
               u.name AS citizen_name,
               c.title AS complaint_title,
               f.created_at
        FROM feedback f
        JOIN complaints c ON f.complaint_id = c.complaint_id
        JOIN users u ON f.user_id = u.user_id
        WHERE 1=1
    """
    params = []

    # Filter by department if not General Admin
    if dept != 'General Admin':
        base_query += " AND c.department=?"
        params.append(dept)

    # Filter by specific complaint if complaint_id is provided
    if complaint_id:
        base_query += " AND f.complaint_id=?"
        params.append(complaint_id)

    # Order by latest feedback first
    base_query += " ORDER BY f.created_at DESC"

    # Execute query
    c.execute(base_query, params)
    feedbacks = c.fetchall()
    conn.close()

    return render_template('admin_feedback.html', feedbacks=feedbacks, admin=admin)


# ----------------- New Complaint -----------------
@app.route('/complaint_new', methods=['GET','POST'])
def complaint_new():
    if 'user_id' not in session or session['role'] != 'citizen':
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        title = request.form.get('title').strip()
        description = request.form.get('description').strip()
        department = request.form.get('category')  # renamed to match frontend
        image_file = request.files.get('image')
        filename = None
        latitude = None
        longitude = None

        # Handle image upload
        if image_file and image_file.filename != '' and allowed_file(image_file.filename):
            filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{image_file.filename}")
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            image_file.save(save_path)
            
            # Try to get GPS from EXIF
            lat, lon = get_exif_location(save_path)
            if lat and lon:
                latitude = str(lat)
                longitude = str(lon)

        # Fallback to form-provided location
        if not latitude or not longitude:
            latitude = request.form.get('latitude')
            longitude = request.form.get('longitude')

        # If still no location, remove uploaded image and return error
        if not latitude or not longitude:
            if filename:
                os.remove(save_path)
            flash("❌ Cannot determine location. Please upload a photo with GPS or provide location.", "danger")
            return redirect(url_for('complaint_new'))

        address = request.form.get('address')
        complaint_date = datetime.now().strftime('%Y-%m-%d')  # save today’s date

        # Insert into DB
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''INSERT INTO complaints 
                     (user_id, title, description, department, image, latitude, longitude, address, created_at) 
                     VALUES (?,?,?,?,?,?,?,?,?)''',
                  (session['user_id'], title, description, department, filename, latitude, longitude, address, complaint_date))
        conn.commit()
        conn.close()

        flash('✅ Complaint submitted successfully', 'success')
        return redirect(url_for('dashboard_user'))

    return render_template('complaint_new.html')


# ----------------- Complaint View -----------------
@app.route('/complaint/<int:cid>')
def complaint_view(cid):
    if 'user_id' not in session:
        flash("Please login first", "warning")
        return redirect(url_for('login'))

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM complaints WHERE complaint_id=?", (cid,))
    complaint = c.fetchone()
    conn.close()

    if not complaint:
        flash("Complaint not found", "danger")
        return redirect(url_for('dashboard_admin'))

    return render_template('complaint_view.html', c=complaint)


# ----------------- Feedback -----------------
@app.route('/feedback/<int:complaint_id>', methods=['GET','POST'])
def feedback(complaint_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    c = conn.cursor()

    # Fetch complaint
    c.execute("SELECT * FROM complaints WHERE complaint_id=?", (complaint_id,))
    complaint = c.fetchone()

    if complaint['status'] != 'Resolved':
        flash('You can give feedback only after your complaint is resolved.', 'warning')
        return redirect(url_for('dashboard_user'))

    if request.method == 'POST':
        feedback_text = request.form['feedback_text']
        rating = int(request.form.get('rating', 0))  # Get rating from form
        c.execute(
            "INSERT INTO feedback (complaint_id, user_id, feedback, rating, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
            (complaint_id, session['user_id'], feedback_text, rating)
        )
        conn.commit()
        conn.close()
        flash('Feedback submitted successfully', 'success')
        return redirect(url_for('dashboard_user'))

    conn.close()
    return render_template('feedback.html', complaint=complaint)



# ----------------- Logout -----------------
@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully','success')
    return redirect(url_for('home'))


# ----------------- Uploaded Files -----------------
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# ----------------- Run App -----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
