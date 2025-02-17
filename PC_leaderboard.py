import serial
import serial.tools.list_ports
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time
import os
import urllib.parse
import socket
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser 

# --- Configuration ---
SERIAL_PORT = None  # Automatically detected if None
BAUD_RATE = 115200
WEB_SERVER_HOST = "0.0.0.0"
WEB_SERVER_PORT = 8080
ADMIN_PASSWORD = "SPSIT"
leaderboard_file = "leaderboard.json"
correct_answers_file = "correct_answers.json"

# --- Category Configuration ---
CATEGORY1_UID_STR = "0xF30xC70x1A0x130x3D"
CATEGORY2_UID_STR = "0x8A0x8D0x570x540x04"
CATEGORY3_UID_STR = "0x120x9C0x190xFA0x6D"

CATEGORY_UIDS = {
    CATEGORY1_UID_STR: "Category1",
    CATEGORY2_UID_STR: "Category2",
    CATEGORY3_UID_STR: "Category3",
}
CATEGORY_NAMES_ADMIN = ["Category 1", "Category 2", "Category 3"]
CATEGORY_NAMES_LEADERBOARD = ["All Categories", "Category 1", "Category 2", "Category 3"]
CATEGORY_NAMES_CONFIG_KEYS = ["Category1", "Category2", "Category3"]  # Keys to access categories in config

# --- Global Variables ---
leaderboard_data = []
correct_answers_config = {"penalty": 60, "categories": {
    "Category1": {},
    "Category2": {},
    "Category3": {},
    "All Categories": {}
}}
PENALTY_PER_INCORRECT = correct_answers_config["penalty"]
NUM_QUESTIONS_PER_CATEGORY = 15  # Define the number of questions, assuming it's consistent

# --- Helper Functions ---

def find_serial_port(root):
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        messagebox.showerror("Error", "No serial ports found. Please ensure your ESP32 is connected.", parent=root)
        return None

    print("Available serial ports:")
    for i, (port, desc, hwid) in enumerate(ports):
        print(f"{i + 1}: {port} {desc} {hwid}")

    if len(ports) == 1:
        print(f"Auto-selecting the only available port: {ports[0].device}")
        return ports[0].device

    # --- Tkinter popup for port selection ---
    port_var = tk.StringVar()
    port_var.set(ports[0].device if ports else "")  # Set default, handle empty list

    def select_port():
        selected_port = port_var.get()
        root.destroy()  # Destroy this window when done.
        nonlocal selected_port_result
        selected_port_result = selected_port

    selected_port_result = None

    # Create radio buttons for each port
    for i, (port, desc, hwid) in enumerate(ports):
        ttk.Radiobutton(root, text=f"{port} ({desc})", variable=port_var, value=port).pack(anchor=tk.W)

    ttk.Button(root, text="Select", command=select_port).pack(pady=10)
    root.protocol("WM_DELETE_WINDOW", select_port) # Ensure select port runs if window closed
    root.mainloop()  # Start *this* window's mainloop

    return selected_port_result

def load_leaderboard():
    global leaderboard_data
    try:
        if os.path.exists(leaderboard_file):
            with open(leaderboard_file, "r") as f:
                leaderboard_data = json.load(f)
            print("Leaderboard loaded from file.")
            # --- Add missing 'disqualified' key to existing entries ---
            for entry in leaderboard_data:
                if "disqualified" not in entry:
                    entry["disqualified"] = False  # Default to False for older entries
        else:
            leaderboard_data = []
            print("Leaderboard file not found, created empty.")
    except Exception as e:
        print(f"Error loading leaderboard: {e}")
        leaderboard_data = []

def save_leaderboard(leaderboard):
    global leaderboard_data
    try:
        with open(leaderboard_file, "w") as f:
            json.dump(leaderboard, f)
        print("Leaderboard saved to file.")
        leaderboard_data = leaderboard
    except Exception as e:
        print(f"Error saving leaderboard: {e}")

def clear_leaderboard():
    global leaderboard_data
    leaderboard_data = []
    save_leaderboard(leaderboard_data)
    print("Leaderboard cleared.")


def add_to_leaderboard(name, time_taken, answers, category):
    global leaderboard_data, correct_answers_config, PENALTY_PER_INCORRECT, NUM_QUESTIONS_PER_CATEGORY
    category_correct_answers = get_correct_answers_for_category(correct_answers_config, category)
    penalty_seconds = 0
    incorrect_answers_count = 0
    unanswered_questions_count = 0
    disqualified = False

    num_questions = len(category_correct_answers) if category_correct_answers else NUM_QUESTIONS_PER_CATEGORY

    if len(answers) < num_questions:  # Check if all questions are answered
        disqualified = True
        print(f"Participant {name} disqualified for not answering all questions.")
    else:
        for question_num in range(1, num_questions + 1):
            question_num_str = str(question_num)
            submitted_answer = answers.get(question_num_str)

            if submitted_answer is None:  # This condition should not be reached if len(answers) check is correct, but keep it for safety
                penalty_seconds += PENALTY_PER_INCORRECT
                unanswered_questions_count += 1
            else:
                correct_answer = category_correct_answers.get(question_num_str)
                if correct_answer and submitted_answer != correct_answer:
                    penalty_seconds += PENALTY_PER_INCORRECT
                    incorrect_answers_count += 1

    penalized_time = time_taken + penalty_seconds

    leaderboard_entry = {"name": name, "time": penalized_time, "penalty": penalty_seconds, "category": category, "disqualified": disqualified}  # Added disqualified status
    leaderboard_data.append(leaderboard_entry)
    leaderboard_data.sort(key=lambda x: (x["disqualified"], x["time"], x["penalty"]))  # Sort by disqualified, then time, then penalty
    save_leaderboard(leaderboard_data)
    print(f"Added to leaderboard: Name={name}, Time={penalized_time} (Penalized), Category={category}, Disqualified={disqualified}")

def format_time(seconds, disqualified=False):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    time_str = "{:02d}:{:02d}:{:02d}".format(hours, minutes, secs)
    if disqualified:
        return "D: " + time_str  # Add "D: " prefix if disqualified
    return time_str

def generate_leaderboard_csv(leaderboard_data):
    csv_data = "Rank;Name;Category;Time;Penalty;Final Time;Status\n"  # Added Status column
    for i, entry in enumerate(leaderboard_data):
        penalty_sec = entry.get("penalty", 0)
        final_time_sec = entry["time"]
        original_time_sec = final_time_sec - penalty_sec if penalty_sec > 0 else final_time_sec
        category = entry.get("category", "N/A")
        disqualified = entry.get("disqualified", False)
        status = "Disqualified" if disqualified else "Qualified"  # Added Status
        csv_data += f"{i + 1};{entry['name']};{category};{format_time(original_time_sec)};{format_time(penalty_sec)};{format_time(final_time_sec, disqualified)};{status}\n"  # Format time with disqualification flag

    return csv_data

def generate_leaderboard_html(leaderboard, selected_category="All Categories"):
    category_buttons_html = """
        <div style="text-align: center; margin-bottom: 20px;">
            <form action="/" method="GET" style="display: inline;">
                <input type="hidden" name="category" value="Category1">
                <button type="submit" class="button-link">Category 1</button>
            </form>
            <form action="/" method="GET" style="display: inline;">
                <input type="hidden" name="category" value="Category2">
                <button type="submit" class="button-link">Category 2</button>
            </form>
            <form action="/" method="GET" style="display: inline;">
                <input type="hidden" name="category" value="Category3">
                <button type="submit" class="button-link">Category 3</button>
            </form>
            <form action="/" method="GET" style="display: inline;">
                <input type="hidden" name="category" value="All Categories">
                <button type="submit" class="button-link">All Categories</button>
            </form>
        </div>
    """
    html_style = """<style>body { font-family: Arial, sans-serif; background-color: #f4f4f4; color: #333; margin: 0; padding: 20px; }.container { width: 80%; max-width: 800px; margin: 20px auto; background-color: white; padding: 30px; border-radius: 10px; box-shadow: 0 0 20px rgba(0, 0, 0, 0.1); }h1 { text-align: center; color: #4472C4; }.header-buttons { position: fixed; top: 10px; left: 10px; right: 10px; display: flex; justify-content: space-between; align-items: center; }.button-link { display: inline-block; padding: 12px 25px; background-color: #428bca; color: white; text-decoration: none; border-radius: 5px; font-size: 1em; transition: background-color 0.3s ease; }.button-link:hover { background-color: #3071a9; }table { border-collapse: collapse; width: 100%; margin: 20px auto; }th, td { border: 1px solid black; padding: 8px; text-align: left; }#leaderboard { display: flex; justify-content: center; }#leaderboard table { width: auto; max-width: 100%; }</style>"""
    html_script_template = """<script>function refreshLeaderboard() {var xhttp = new XMLHttpRequest();xhttp.onreadystatechange = function() {if (this.readyState == 4 && this.status == 200) {document.getElementById("leaderboard").innerHTML = this.responseText;}};xhttp.open("GET", "/leaderboard_table?category=%s", true);xhttp.send();}</script>"""
    html_script = html_script_template % selected_category
    html_content = f"""<!DOCTYPE html><html><head><title>ESP32 Leaderboard</title>{html_style}{html_script}</head><body onload="refreshLeaderboard(); setInterval(refreshLeaderboard, 15000);"><div class="header-buttons"><a href="/admin" class="button-link" style="background-color: green;">Admin Page</a></div><div class="container"><h1>ESP32 Leaderboard - {selected_category}</h1>{category_buttons_html}<div id="leaderboard"><!-- Leaderboard table will be loaded here --></div></div></body></html>"""
    return html_content

def generate_leaderboard_table_html(leaderboard):
    table_html = """<table><thead><tr><th>Rank</th><th>Name</th><th>Category</th><th>Time</th><th>Penalty</th><th>Final Time</th><th>Status</th></tr></thead><tbody>"""  # Added Status column header
    for i, entry in enumerate(leaderboard):
        penalty_sec = entry.get("penalty", 0)
        final_time_sec = entry["time"]
        original_time_sec = final_time_sec - penalty_sec if penalty_sec > 0 else final_time_sec
        category = entry.get("category", "N/A")
        disqualified = entry.get("disqualified", False)
        status = "Disqualified" if disqualified else "Qualified" 
        table_html += f"""<tr><td>{i + 1}</td><td>{entry['name']}</td><td>{category}</td><td>{format_time(original_time_sec)}</td><td>{format_time(penalty_sec)}</td><td>{format_time(final_time_sec, disqualified)}</td><td>{status}</td></tr>"""  # Format time with disqualification flag and add status
    table_html += """</tbody></table>"""
    return table_html

def generate_admin_html(config):
    penalty = config.get("penalty", 60)
    category_names = CATEGORY_NAMES_ADMIN
    category_config_keys = CATEGORY_NAMES_CONFIG_KEYS

    admin_page_style = """
    <style>
    body { font-family: Arial, sans-serif; background-color: #f4f4f4; color: #333; margin: 0; padding: 20px; }
    .container { width: 80%; max-width: 1200px; /* Increased max-width */ margin: 20px auto; background-color: white; padding: 30px; border-radius: 10px; box-shadow: 0 0 20px rgba(0, 0, 0, 0.1); }
    h1 { text-align: center; color: #4472C4; }
    h2 { color: #4472C4; margin-top: 25px; border-bottom: 1px solid #eee; padding-bottom: 5px; }
    label { display: block; margin-top: 15px; font-weight: bold; }
    input[type="number"], select, input[type="password"] { width: calc(100% - 20px); padding: 10px; margin-top: 8px; margin-bottom: 15px; border: 1px solid #ddd; border-radius: 5px; box-sizing: border-box; font-size: 1em; }
    select { appearance: none; -webkit-appearance: none; -moz-appearance: none; background-image: url('data:image/svg+xml;utf8,<svg fill="black" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M7 10l5 5 5-5z"/><path d="M0 0h24v24H0z" fill="none"/></svg>'); background-repeat: no-repeat; background-position-x: 100%; background-position-y: 5px; }
    .button-link, .button-link2, .export-button, .reset-button, button[type="submit"] { display: block; width: 200px; max-width: 200px; padding: 12px 25px; margin: 15px auto; background-color: #5cb85c; color: white; text-decoration: none; border-radius: 5px; border: none; cursor: pointer; font-size: 1em; transition: background-color 0.3s ease; text-align: center; box-sizing: border-box; }
    button:hover, .button-link:hover, .button-link2:hover, .reset-button:hover, .export-button:hover { background-color: #4cae4c; }
    .button-link { background-color: #428bca; }
    .button-link:hover { background-color: #3071a9; }
    .button-link2 { background-color: #5bc0de; color: white; }
    .button-link2:hover { background-color: #31b0d5; }
    .reset-button { background-color: #d9534f; }
    .reset-button:hover { background-color: #c9302c; }
    .export-button { background-color: orange; }
    .export-button:hover { background-color: darkorange; }
    .button-container, .button-container2, .reset-button-container, .export-button-container { text-align: center; margin-top: 20px; }
    .reset-section { margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; }
    .form-group { margin-bottom: 20px; }
    .form-group:last-child { margin-bottom: 0; }
    .category-container { display: flex; justify-content: space-between; flex-wrap: wrap; }
    .category-section { width: 30%; /* Adjust as needed */ border: 1px solid #ddd; padding: 15px; margin-bottom: 20px; border-radius: 5px; background-color: #f9f9f9; }
    .category-section h3 { text-align: center; color: #4472C4; }
     .category-answers-box { margin-top: 10px;}
    </style>
    """

    html_content = f"""<!DOCTYPE html>
    <html>
    <head>
        <title>ESP32 Admin - Set Correct Answers and Penalty</title>
        {admin_page_style}
        <script>
            function checkPasswordAndReset() {{
                var password = document.getElementById('resetPassword').value;
                if (password === '{ADMIN_PASSWORD}') {{
                    if (confirm('Are you sure you want to reset the leaderboard? This action cannot be undone.')) {{
                        var xhr = new XMLHttpRequest();
                        xhr.open('POST', '/admin_reset', true);
                        xhr.setRequestHeader('Content-type', 'application/x-www-form-urlencoded');
                        xhr.onload = function () {{
                            if (xhr.status == 200) {{
                                alert('Leaderboard reset successfully!');
                                window.location.href = '/admin';
                            }} else {{
                                alert('Error resetting leaderboard.');
                            }}
                        }};
                        xhr.send('password=' + password);
                    }}
                }} else {{
                    alert('Incorrect password. Reset aborted.');
                }}
            }}

            window.addEventListener('load', function() {{
                window.adminConfig = {{}};
                try {{
                    window.adminConfig = JSON.parse(document.getElementById('adminConfigJson').textContent);
                }} catch (e) {{
                    console.error("Error parsing adminConfigJson:", e);
                }}
                 // No need to call onCategoryChange here, as we're displaying all at once.
            }});

        </script>
    </head>
    <body>
        <div class="container">
            <h1>Admin - Correct Answers and Penalty</h1>
            <form action="/save_answers" method="post">
                <div class="form-group">
                    <label for="penalty">Penalty per Incorrect Answer (seconds):</label>
                    <input type="number" id="penalty" name="penalty" value="{penalty}" required>
                </div>
                <div style="display:none;" id="adminConfigJson">{json.dumps(config)}</div>

                <div class="category-container">
    """

    # Generate HTML for each category
    for i, category_key in enumerate(category_config_keys):
        category_name = category_names[i]
        category_answers = config["categories"].get(category_key, {})

        html_content += f"""
                    <div class="category-section">
                        <h3>{category_name}</h3>
                        <div class="category-answers-box">
        """

        for q_num in range(1, 16):
            question_num_str = str(q_num)
            current_answer = category_answers.get(question_num_str, "")
            html_content += f"""
                            <div class="form-group">
                                <label for="answer_{category_key}_{q_num}">Question {q_num}:</label>
                                <select id="answer_{category_key}_{q_num}" name="answer_{category_key}_{q_num}">
            """

            answer_options = ["A", "B", "C", "D", ""]  # Options including "" (Not Set)
            option_texts = ["A", "B", "C", "D", "Not Set"]

            for j, option_value in enumerate(answer_options):
                selected = "selected" if option_value == current_answer else ""
                html_content += f'<option value="{option_value}" {selected}>{option_texts[j]}</option>'

            html_content += f"""
                                </select>
                            </div>
            """
        html_content += """
                        </div>
                    </div>
        """

    html_content += """
                </div>
                <div class="button-container">
                    <button type="submit" class="button-link2">Save Settings</button>
                </div>
            </form>

            <div class="export-button-container">
                <a href="/leaderboard_excel" class="export-button">Export All Categories to Excel</a> <br>
                <a href="/leaderboard_excel_category?category=Category1" class="export-button">Export Category 1 to Excel</a><br>
                <a href="/leaderboard_excel_category?category=Category2" class="export-button">Export Category 2 to Excel</a><br>
                <a href="/leaderboard_excel_category?category=Category3" class="export-button">Export Category 3 to Excel</a>
            </div>
            <div class="reset-section">
                <h2>Reset Leaderboard</h2>
                <div class="form-group">
                    <label for="resetPassword">Admin Password:</label>
                    <input type="password" id="resetPassword" name="resetPassword">
                </div>
                <div class="reset-button-container">
                    <button onclick="checkPasswordAndReset()" class="reset-button">Reset Leaderboard</button>
                </div>
            </div>
            <div class="button-container2">
                <a href="/" class="button-link">Back to Leaderboard</a>
            </div>
        </div>
    </body>
    </html>
    """

    return html_content

def get_category_name_from_uid_str(uid_str):
    return CATEGORY_UIDS.get(uid_str, "All Categories")

def load_correct_answers_config():
    global correct_answers_config, PENALTY_PER_INCORRECT
    default_config = {"penalty": 60, "categories": {
        "Category1": {},
        "Category2": {},
        "Category3": {},
        "All Categories": {}
    }}
    try:
        if os.path.exists(correct_answers_file):
            with open(correct_answers_file, "r") as f:
                config = json.load(f)
                if isinstance(config, dict) and "penalty" in config and "categories" in config:
                    correct_answers_config = config
                    PENALTY_PER_INCORRECT = correct_answers_config["penalty"]
                    print("Correct answers config loaded from file.")
                    return
                else:
                    print("Warning: Config file content is invalid structure. Using default.")
                    correct_answers_config = default_config
        else:
            print("Correct answers config file not found, using default.")
            correct_answers_config = default_config
    except Exception as e:
        print(f"Error loading correct answers config: {e}. Using default.")
        correct_answers_config = default_config

def save_correct_answers_config(config):
    global correct_answers_config, PENALTY_PER_INCORRECT
    try:
        with open(correct_answers_file, "w") as f:
            json.dump(config, f)
        print("Correct answers and penalty config saved to file.")
        correct_answers_config = config
        PENALTY_PER_INCORRECT = correct_answers_config["penalty"]
    except Exception as e:
        print(f"Error saving correct answers config to file: {e}")

def get_correct_answers_for_category(config, category_name):
    categories = config.get("categories", {})
    return categories.get(category_name, {})

def filter_leaderboard_by_category(leaderboard, category):
    if category == "All Categories":
        return leaderboard
    else:
        return [entry for entry in leaderboard if entry.get("category") == category]
# --- Serial Listener Thread ---
def serial_listener():
    global leaderboard_data, correct_answers_config
    try:
        if SERIAL_PORT is None:
            print("Serial port must be selected before starting the listener.") #This will be selected before starting serial thread
            return

        serial_connection = serial.Serial(SERIAL_PORT, BAUD_RATE)
        print(f"Listening on serial port: {SERIAL_PORT}")


        while True:
            if serial_connection.in_waiting > 0:
                data_bytes = serial_connection.readline()
                try:
                    data_str = data_bytes.decode('utf-8').strip()
                    try:
                        json_data = json.loads(data_str)
                        if "name" in json_data and "time" in json_data and "answers" in json_data and "category_uid" in json_data:
                            name = json_data["name"]
                            time_taken = json_data["time"]
                            answers_data = json_data["answers"]
                            category_uid_str = json_data["category_uid"]
                            category_name = get_category_name_from_uid_str(category_uid_str) if category_uid_str else "All Categories"
                            add_to_leaderboard(name, time_taken, answers_data, category_name)
                        else:
                            print("JSON data missing required fields.")
                    except json.JSONDecodeError:
                        print("Invalid JSON data received.")
                except UnicodeDecodeError:
                    print("UnicodeDecodeError decoding serial data.")
    except serial.SerialException as e:
        print(f"Serial port error: {e}")
    except KeyboardInterrupt:
        print("Serial listener stopped.")
    finally:
        if 'serial_connection' in locals() and serial_connection.is_open:
            serial_connection.close()

# --- Web Request Handler ---
class SimpleRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global leaderboard_data, correct_answers_config
        path = self.path
        print(f"do_GET: self.path = '{path}'")  # Debug: Print self.path

        if "?" in path:
            base_path = path.split("?", 1)[0]
        else:
            base_path = path
        print(f"do_GET: base_path = '{base_path}'")  # Debug: Print base_path

        if base_path == "/":
            print("do_GET: Entering path '/' block")  # Debug: Entering '/' block
            self.handle_leaderboard_page()
        elif base_path == "/admin":
            print("do_GET: Entering path '/admin' block")  # Debug: Entering '/admin' block
            self.handle_admin_page()
        elif base_path == "/leaderboard_table":
            print("do_GET: Entering path '/leaderboard_table' block")  # Debug: Entering '/leaderboard_table' block
            self.handle_leaderboard_table()
        elif base_path == "/leaderboard_excel":
            print("do_GET: Entering path '/leaderboard_excel' block")  # Debug: Entering '/leaderboard_excel' block
            self.handle_excel_export()
        elif base_path.startswith("/leaderboard_excel_category"):
            print("do_GET: Entering path '/leaderboard_excel_category' block")  # Debug: Entering '/leaderboard_excel_category' block
            self.handle_excel_category_export()
        else:
            print("do_GET: No matching path found. Sending 404.")  # Debug: No match
            self.send_error(404)

    def do_POST(self):
        path = self.path
        if path == "/save_answers":
            self.handle_save_answers()
        elif path == "/admin_reset":
            self.handle_admin_reset()
        elif path == "/add":
            self.send_error(405, "Method Not Allowed", "Data should be sent via serial.")  # Method Not Allowed
        else:
            self.send_error(404)

    def get_query_param(self, param_name):
        query = self.path.split('?', 1)
        if len(query) > 1:
            params = query[1].split('&')
            for param in params:
                key_value = param.split('=', 1)
                if key_value[0] == param_name:
                    return urllib.parse.unquote_plus(key_value[1])  # Decode URL-encoded parameters
        return None

    def handle_leaderboard_page(self):
        selected_category = self.get_query_param("category")
        if not selected_category:
            selected_category = "All Categories"
        filtered_leaderboard = filter_leaderboard_by_category(leaderboard_data, selected_category)
        html = generate_leaderboard_html(filtered_leaderboard, selected_category)
        self.send_html_response(html)

    def handle_leaderboard_table(self):
        selected_category = self.get_query_param("category")
        if not selected_category:
            selected_category = "All Categories"
        filtered_leaderboard = filter_leaderboard_by_category(leaderboard_data, selected_category)
        table_html = generate_leaderboard_table_html(filtered_leaderboard)
        self.send_html_response(table_html)

    def handle_admin_page(self):
        admin_html = generate_admin_html(correct_answers_config)
        self.send_html_response(admin_html)

    def handle_excel_export(self):
        csv_data = generate_leaderboard_csv(leaderboard_data)
        self.send_csv_response(csv_data, "leaderboard_all_categories.csv")

    def handle_excel_category_export(self):
        category_name = self.get_query_param("category")
        if not category_name:
            category_name = "All Categories"
        filtered_leaderboard = filter_leaderboard_by_category(leaderboard_data, category_name)
        csv_data = generate_leaderboard_csv(filtered_leaderboard)
        filename = f"leaderboard_{category_name.replace(' ', '_')}.csv"
        self.send_csv_response(csv_data, filename)

    def handle_save_answers(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        form_data = urllib.parse.parse_qs(post_data)

        updated_penalty = int(form_data.get("penalty", [60])[0])
        correct_answers_config["penalty"] = updated_penalty

        # Iterate through all possible answer fields
        for category_key in CATEGORY_NAMES_CONFIG_KEYS:
            updated_correct_answers = {}
            for q_num in range(1, 16):
                answer_key = f"answer_{category_key}_{q_num}"
                answer_list = form_data.get(answer_key, [""])
                answer = answer_list[0]  # Take the first if multiple
                if answer: 
                    updated_correct_answers[str(q_num)] = answer
            correct_answers_config["categories"][category_key] = updated_correct_answers

        save_correct_answers_config(correct_answers_config)
        self.send_redirect_response("/admin")

    def handle_admin_reset(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        form_data = {}
        for item in post_data.split('&'):
            key, value = item.split('=')
            form_data[key] = value
        password_attempt = form_data.get("password")

        if password_attempt == ADMIN_PASSWORD:
            clear_leaderboard()
            self.send_redirect_response("/admin")
        else:
            self.send_error(403, "Forbidden", "Incorrect Admin Password")

    def send_html_response(self, html_content):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(html_content.encode())

    def send_csv_response(self, csv_data, filename):
        self.send_response(200)
        self.send_header("Content-type", "text/csv")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(csv_data.encode())

    def send_redirect_response(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

# --- Get IP and Show Popup ---
def get_server_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "127.0.0.1"

def show_ip_popup(ip_address, port):
    """Displays a Tkinter popup with the server's IP address and port."""
    root = tk.Tk()  
    root.title("Server Information")
    root.geometry("300x100") 


    # IP address as a clickable link
    message_label = tk.Label(root, text=f"Web server started at:")
    message_label.pack(pady=(10,0))

    link = tk.Label(root, text=f"http://{ip_address}:{port}", fg="blue", cursor="hand2")
    link.pack()
    link.bind("<Button-1>", lambda e: open_url(f"http://{ip_address}:{port}"))
    
    root.after(5000, root.destroy)  
    root.mainloop()

def open_url(url):
    """Opens the given URL in the default web browser."""
    webbrowser.open(url)


# --- Run Web Server ---
def run_web_server(ip_address, port):
    web_server = HTTPServer((WEB_SERVER_HOST, port), SimpleRequestHandler)
    print(f"Web server started at http://{ip_address}:{port}")
    try:
        web_server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        web_server.server_close()
        print("Web server stopped.")


# --- Main Execution ---
if __name__ == "__main__":
    load_leaderboard()
    load_correct_answers_config()

    # 1. Find Serial Port (using Tkinter popup) and create main window
    root_serial = tk.Tk()
    root_serial.title("Select Serial Port")
    port = find_serial_port(root_serial)  # This will now use its *own* mainloop

    if port:
        SERIAL_PORT = port

        # 2.  Start serial thread
        serial_thread = threading.Thread(target=serial_listener)
        serial_thread.daemon = True
        serial_thread.start()

        # 3. Get and display server IP (in its own popup)
        local_ip = get_server_ip()
        show_ip_popup(local_ip, WEB_SERVER_PORT)  # This now creates its own root

        # 4. Start Web Server (in a separate thread)
        web_server_thread = threading.Thread(target=run_web_server, args=(local_ip, WEB_SERVER_PORT))
        web_server_thread.daemon = True
        web_server_thread.start()

        # We don't need a mainloop here anymore, as we handle UI in separate functions
        # with their own root windows.
        while True:  # Keep the main thread alive
            time.sleep(1)

    else:
       print("No serial port selected. Exiting.") # Error already displayed in find_serial_ports.
