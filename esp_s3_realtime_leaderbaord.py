# server.py
import network
import usocket as socket
import time
import json

# --- Wi-Fi Configuration ---
ap = network.WLAN(network.AP_IF)
ap.active(True)
ap.config(essid="MyESP32S3AP", password="yourpassword", channel=6, authmode=network.AUTH_WPA_WPA2_PSK)

while ap.active() == False:
    pass

print("AP created. IP:", ap.ifconfig()[0])

# --- Leaderboard Data ---
leaderboard_file = "leaderboard.json"
correct_answers_file = "correct_answers.json"
ADMIN_PASSWORD = "SPSIT"  # Set admin password

# --- Category Configuration ---
CATEGORY1_UID_STR = "0xF30xC70x1A0x130x3D"  # Category 1 UID (and Start UID on client)
CATEGORY2_UID_STR = "0x8A0x8D0x570x540x04"  # Category 2 UID (and Start UID on client)
CATEGORY3_UID_STR = "0x120x9C0x190xFA0x6D"  # Category 3 UID (and Start UID on client)

CATEGORY_UIDS = {
    CATEGORY1_UID_STR: "Category1",
    CATEGORY2_UID_STR: "Category2",
    CATEGORY3_UID_STR: "Category3",
}
CATEGORY_NAMES = ["All Categories", "Category1", "Category2", "Category3"] # For display in dropdown

def get_category_name_from_uid_str(uid_str):
    """Returns category name based on UID string or "All Categories" if not found."""
    return CATEGORY_UIDS.get(uid_str, "All Categories")

def load_leaderboard():
    """Loads leaderboard data from a JSON file."""
    try:
        with open(leaderboard_file, "r") as f:
            leaderboard = json.load(f)
        print("Leaderboard loaded from file.")
    except OSError:
        leaderboard = []
        print("Leaderboard file not found, created empty.")
    return leaderboard

def save_leaderboard(leaderboard):
    """Saves leaderboard data to a JSON file."""
    try:
        with open(leaderboard_file, "w") as f:
            json.dump(leaderboard, f)
        print("Leaderboard saved to file.")
    except Exception as e:
        print("Error saving leaderboard to file: {}".format(e)) # use .format instead of f-string

def load_correct_answers_config():
    """Loads correct answers and penalty config from a JSON file."""
    default_config = {"penalty": 60, "answers": {}}
    print("load_correct_answers_config: Starting to load config...")

    try:
        print("load_correct_answers_config: Attempting to open file: '{}'".format(correct_answers_file)) # use .format instead of f-string
        with open(correct_answers_file, "r") as f:
            print("load_correct_answers_config: File opened successfully.")
            try:
                config = json.load(f)
                print("load_correct_answers_config: JSON loaded successfully. Content:", config)
                if isinstance(config, dict) and "penalty" in config and "answers" in config:
                    print("load_correct_answers_config: Config is valid, returning loaded config.")
                    return config
                else:
                    print("load_correct_answers_config: Warning: Config file content is invalid structure. Using default.")
                    return default_config
            except ValueError as json_err:
                print("load_correct_answers_config: ERROR: JSON Decode Error: {}. Using default config.".format(json_err)) # use .format instead of f-string
                return default_config
    except OSError as os_err:
        if os_err.args[0] == 2:
            print("load_correct_answers_config: FileNotFoundError: {}. Using default config.".format(os_err)) # use .format instead of f-string
        else:
            print("load_correct_answers_config: OSError opening file: {}. Using default config.".format(os_err)) # use .format instead of f-string
        return default_config
    except Exception as general_err:
        print("load_correct_answers_config: ERROR: Unexpected Exception: {}. Using default config.".format(general_err)) # use .format instead of f-string
        return default_config
    #else: # Removed else clause after try-except for better micropython compatibility
    #    print("load_correct_answers_config: WARNING: Reached ELSE clause of outer try-except, should not happen. Returning default config as fallback.")
    #    return default_config

    print("load_correct_answers_config: WARNING: Reached end of function unexpectedly, should not happen. Returning default config as fallback.")
    return default_config

def save_correct_answers_config(config):
    """Saves correct answers and penalty config to a JSON file."""
    try:
        with open(correct_answers_file, "w") as f:
            json.dump(config, f)
        print("Correct answers and penalty config saved to file.")
    except Exception as e:
        print("Error saving correct answers and penalty config to file: {}".format(e)) # use .format instead of f-string

correct_answers_config = load_correct_answers_config()
correct_answers = correct_answers_config["answers"]
PENALTY_PER_INCORRECT = correct_answers_config["penalty"]

def add_to_leaderboard(name, time_taken, answers, category="All Categories"): # Added category parameter
    """Adds a new entry to the leaderboard, calculates penalty, and sorts it."""
    leaderboard = load_leaderboard()
    correct_answers_config = load_correct_answers_config()
    correct_answers = correct_answers_config["answers"]
    PENALTY_PER_INCORRECT = correct_answers_config["penalty"]

    penalty_seconds = 0
    incorrect_answers_count = 0
    unanswered_questions_count = 0

    num_questions = len(correct_answers) if correct_answers else 15

    for question_num in range(1, num_questions + 1):
        question_num_str = str(question_num)
        submitted_answer = answers.get(question_num_str)

        if submitted_answer is None:
            penalty_seconds += PENALTY_PER_INCORRECT
            unanswered_questions_count += 1
            print("Question {} unanswered - Penalty applied.".format(question_num)) # use .format instead of f-string
        else:
            correct_answer = correct_answers.get(question_num_str)
            if correct_answer and submitted_answer != correct_answer:
                penalty_seconds += PENALTY_PER_INCORRECT
                incorrect_answers_count += 1

    penalized_time = time_taken + penalty_seconds
    print("Incorrect answers: {}, Unanswered questions: {}, Penalty: {} seconds".format(incorrect_answers_count, unanswered_questions_count, penalty_seconds)) # use .format instead of f-string
    print("Penalized Time: {} seconds".format(penalized_time)) # use .format instead of f-string

    leaderboard.append({"name": name, "time": penalized_time, "penalty": penalty_seconds, "category": category}) # Added category to entry
    leaderboard.sort(key=lambda x: x["time"])
    save_leaderboard(leaderboard)
    print("Added to leaderboard: Name={}, Time={} (Penalized), Category={}".format(name, penalized_time, category)) # use .format instead of f-string

def clear_leaderboard():
    """Clears all entries from the leaderboard."""
    save_leaderboard([])
    print("Leaderboard cleared.")

def format_time(seconds):
    """Converts seconds to HH:MM:SS format, handling potential float input."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return "{:02d}:{:02d}:{:02d}".format(hours, minutes, secs)

def generate_leaderboard_csv(leaderboard):
    """Generates CSV data from the leaderboard data."""
    csv_data = "Rank,Name,Category,Time,Penalty,Final Time\n" # Added Category to CSV header
    for i, entry in enumerate(leaderboard):
        penalty_sec = entry.get("penalty", 0)
        final_time_sec = entry["time"]
        original_time_sec = final_time_sec - penalty_sec if penalty_sec > 0 else final_time_sec
        csv_data += "{},{},{},{},{},{}\n".format(i + 1, entry['name'], entry.get('category', 'N/A'), format_time(original_time_sec), format_time(penalty_sec), format_time(final_time_sec)) # use .format instead of f-string, Added Category to CSV row
    return csv_data

# --- HTML for Webpages ---
def generate_leaderboard_html(leaderboard, selected_category="All Categories"):
    """Generates the HTML content for the leaderboard webpage."""

    category_buttons_html = """
        <div style="text-align: center; margin-bottom: 20px;">
            <form action="/" method="GET" style="display: inline;">
                <input type="hidden" name="category" value="All Categories">
                <button type="submit" class="button-link" style="background-color: #555;">All Categories</button>
            </form>
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
        </div>
    """

    html_style = """
<style>
body { font-family: Arial, sans-serif; background-color: #f4f4f4; color: #333; margin: 0; padding: 20px; }
.container { width: 80%; max-width: 800px; margin: 20px auto; background-color: white; padding: 30px; border-radius: 10px; box-shadow: 0 0 20px rgba(0, 0, 0, 0.1); }
h1 { text-align: center; color: #4472C4; }
.header-buttons {
    position: fixed;
    top: 10px;
    left: 10px;
    right: 10px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.button-link { display: inline-block; padding: 12px 25px; background-color: #428bca; color: white; text-decoration: none; border-radius: 5px; font-size: 1em; transition: background-color 0.3s ease; }
.button-link:hover { background-color: #3071a9; }

table { border-collapse: collapse; width: 100%; margin: 20px auto; }
th, td { border: 1px solid black; padding: 8px; text-align: left; }
#leaderboard { display: flex; justify-content: center; }
#leaderboard table { width: auto; max-width: 100%; }
</style>
"""

    html_script_template = """
    <script>
        function refreshLeaderboard() {
            var xhttp = new XMLHttpRequest();
            xhttp.onreadystatechange = function() {
                if (this.readyState == 4 && this.status == 200) {
                    document.getElementById("leaderboard").innerHTML = this.responseText;
                }
            };
            xhttp.open("GET", "/leaderboard_table?category=%s", true);
            xhttp.send();
        }
    </script>
    """
    html_script = html_script_template % selected_category

    html_content = """
<!DOCTYPE html>
<html>
<head>
<title>ESP32 Leaderboard</title>
{}
{}
</head>
<body onload="refreshLeaderboard(); setInterval(refreshLeaderboard, 15000);">
    <div class="header-buttons">
        <a href="/admin" class="button-link" style="background-color: green;">Admin Page</a>
    </div>
    <div class="container">
        <h1>ESP32 Leaderboard - {}</h1>
        {}
        <div id="leaderboard">
            <!-- Leaderboard table will be loaded here -->
        </div>
    </div>
</body>
</html>
"""
    html = html_content.format(html_style, html_script, selected_category, category_buttons_html)
    return html

def generate_leaderboard_table_html(leaderboard):
    """Generates the HTML for the leaderboard table."""
    table_html = """
<table>
<thead>
<tr>
<th>Rank</th>
<th>Name</th>
<th>Category</th>
<th>Time</th>
<th>Penalty</th>
<th>Final Time</th>
</tr>
</thead>
<tbody>
"""
    for i, entry in enumerate(leaderboard):
        penalty_sec = entry.get("penalty", 0)
        final_time_sec = entry["time"]
        original_time_sec = final_time_sec - penalty_sec if penalty_sec > 0 else final_time_sec
        category = entry.get("category", "N/A") # Get category, default to "N/A" if missing

        table_html += """
        <tr>
            <td>{}</td>
            <td>{}</td>
            <td>{}</td>
            <td>{}</td>
            <td>{}</td>
            <td>{}</td>
        </tr>
        """.format(i + 1, entry['name'], category, format_time(original_time_sec), format_time(penalty_sec), format_time(final_time_sec)) # use .format instead of f-string
    table_html += """
    </tbody>
</table>
"""
    return table_html

def generate_admin_html(config):
    """Generates the HTML for the admin page to set correct answers and penalty."""
    penalty = config.get("penalty", 60)
    current_correct_answers = config.get("answers", {})

    admin_page_style = """
        <style>
            body { font-family: Arial, sans-serif; background-color: #f4f4f4; color: #333; margin: 0; padding: 20px; }
            .container { width: 80%; max-width: 800px; margin: 20px auto; background-color: white; padding: 30px; border-radius: 10px; box-shadow: 0 0 20px rgba(0, 0, 0, 0.1); }
            h1 { text-align: center; color: #4472C4; }
            h2 { color: #4472C4; margin-top: 25px; border-bottom: 1px solid #eee; padding-bottom: 5px; }
            label { display: block; margin-top: 15px; font-weight: bold; }
            input[type="number"], select, input[type="password"] { width: calc(100% - 20px); padding: 10px; margin-top: 8px; margin-bottom: 15px; border: 1px solid #ddd; border-radius: 5px; box-sizing: border-box; font-size: 1em; }
            select { appearance: none; -webkit-appearance: none; -moz-appearance: none; background-image: url('data:image/svg+xml;utf8,<svg fill="black" height="24" viewBox="0 0 24 24" width="24" xmlns="http://www.w3.org/2000/svg"><path d="M7 10l5 5 5-5z"/><path d="M0 0h24v24H0z" fill="none"/></svg>'); background-repeat: no-repeat; background-position-x: 100%; background-position-y: 5px; } /* Custom arrow for select */
            button, .button-link, .button-link2, .reset-button, .export-button { display: inline-block; padding: 12px 25px; background-color: #5cb85c; color: white; text-decoration: none; border-radius: 5px; border: none; cursor: pointer; font-size: 1em; transition: background-color 0.3s ease; margin-top: 10px; }
            button:hover, .button-link:hover, .button-link2:hover, .reset-button:hover, .export-button:hover { background-color: #4cae4c; }
            .button-link { background-color: #428bca; }
            .button-link:hover { background-color: #3071a9; }
            .button-link2 { background-color: #5bc0de; color: white; } /* Example different button */
            .button-link2:hover { background-color: #31b0d5; }
            .reset-button { background-color: #d9534f; }
            .reset-button:hover { background-color: #c9302c; }
            .export-button { background-color: orange; }
            .export-button:hover { background-color: darkorange; }
            .button-container, .button-container2, .reset-button-container, .export-button-container { text-align: center; margin-top: 20px; }
            .button-link, .button-link2, .export-button { width: auto; display: block; margin: 15px auto; max-width: 200px; } /* Button links as blocks */
            .reset-section { margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; }
            .form-group { margin-bottom: 20px; }
            .form-group:last-child { margin-bottom: 0; }
        </style>
    """

    html = """
<!DOCTYPE html>
<html>
<head>
    <title>ESP32 Admin - Set Correct Answers and Penalty</title>
    {}
    <script>
        function checkPasswordAndReset() {{
            var password = document.getElementById('resetPassword').value;
            if (password === '{}') {{
                if (confirm('Are you sure you want to reset the leaderboard? This action cannot be undone.')) {{
                    var xhr = new XMLHttpRequest();
                    xhr.open('POST', '/admin_reset', true);
                    xhr.setRequestHeader('Content-type', 'application/x-www-form-urlencoded');
                    xhr.onload = function () {{
                        if (xhr.status == 200) {{
                            alert('Leaderboard reset successfully!');
                            window.location.href = '/admin'; // Refresh admin page to show empty leaderboard
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
    </script>
</head>
<body>
    <div class="container">
        <h1>Admin - Correct Answers and Penalty</h1>
        <form action="/save_answers" method="post">
            <div class="form-group">
                <label for="penalty">Penalty per Incorrect Answer (seconds):</label>
                <input type="number" id="penalty" name="penalty" value="{}" required>
            </div>""".format(admin_page_style, ADMIN_PASSWORD, str(penalty)) # use .format instead of f-string
    for i in range(1, 16):
        question_num = str(i)
        current_answer = current_correct_answers.get(question_num, "")

        option_a_selected = 'selected' if current_answer == 'A' else ''
        option_b_selected = 'selected' if current_answer == 'B' else ''
        option_c_selected = 'selected' if current_answer == 'C' else ''
        option_d_selected = 'selected' if current_answer == 'D' else ''
        option_empty_selected = 'selected' if current_answer == '' else ''


        html += """
            <div class="form-group">
                <label for="answer{}">Question {}:</label>
                <select id="answer{}" name="answer{}">
                    <option value="A" {}>A</option>
                    <option value="B" {}>B</option>
                    <option value="C" {}>C</option>
                    <option value="D" {}>D</option>
                    <option value=""  {}>Not Set</option>
                </select>
            </div>""".format(i, i, i, i, option_a_selected, option_b_selected, option_c_selected, option_d_selected, option_empty_selected) # use .format instead of f-string
    html += """
            <div class="button-container">
                <button type="submit" class="button-link2" >Save Settings</button>
            </div>
        </form>

        <div class="export-button-container">
            <a href="/leaderboard_excel" class="export-button">Export to Excel</a>
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
    return html

# --- Socket Server ---
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(("", 80))
s.listen(5)

while True:
    conn, addr = s.accept()
    print("Got a connection from", addr)
    request = conn.recv(1024).decode("utf-8")

    # --- Handle HTTP Requests ---
    request_lines = request.split("\r\n")
    request_line = request_lines[0]
    method, path_raw, _ = request_line.split(" ")

    # Extract base path (part before '?')
    if "?" in path_raw:
        path_base = path_raw.split("?")[0]
    else:
        path_base = path_raw

    print(f"Full Request:\n{request}") # Debug: Print full request
    print(f"Request Method: {method}, Path (raw): {path_raw}, Path (base): {path_base}") # Debug: Print method and both paths


    def get_query_param(request_str, param_name):
        """Helper function to extract query parameters from a request string."""
        try:
            path_and_query = request_str.split(" ")[1]
            if "?" in path_and_query:
                query_str = path_and_query.split("?")[1]
                params = query_str.split("&")
                for param in params:
                    key_value = param.split("=")
                    if key_value[0] == param_name:
                        return key_value[1]
            return None
        except:
            return None

    def filter_leaderboard_by_category(leaderboard, category):
        """Filters leaderboard entries by category."""
        print(f"Filtering leaderboard for category: {category}") # Debug print
        if category == "All Categories":
            print("   Returning ALL categories") # Debug print
            return leaderboard
        else:
            filtered_list = [entry for entry in leaderboard if entry.get("category") == category]
            print(f"   Returning {len(filtered_list)} entries for category: {category}") # Debug print
            return filtered_list


    if method == "GET" and path_base == "/": # Use path_base here
        selected_category = get_query_param(request, "category")
        if not selected_category:
            selected_category = "All Categories"  # Default category
        print(f"Request for leaderboard page, selected_category: {selected_category}") # Debug print
        leaderboard = load_leaderboard()
        filtered_leaderboard = filter_leaderboard_by_category(leaderboard, selected_category)
        html = generate_leaderboard_html(filtered_leaderboard, selected_category)
        conn.sendall(("HTTP/1.1 200 OK\nContent-Type: text/html\n\n{}".format(html)).encode()) # use .format instead of f-string
    elif method == "GET" and path_base == "/leaderboard_table": # Use path_base here
        selected_category = get_query_param(request, "category")
        if not selected_category:
            selected_category = "All Categories" # Default if not provided
        print(f"Request for leaderboard table, selected_category: {selected_category}") # Debug print
        leaderboard = load_leaderboard()
        filtered_leaderboard = filter_leaderboard_by_category(leaderboard, selected_category)
        table_html = generate_leaderboard_table_html(filtered_leaderboard)
        conn.sendall(("HTTP/1.1 200 OK\nContent-Type: text/html\n\n{}".format(table_html)).encode()) # use .format instead of f-string
    elif method == "GET" and path_base == "/admin": # Use path_base here
        admin_html = generate_admin_html(correct_answers_config)
        conn.sendall(("HTTP/1.1 200 OK\nContent-Type: text/html\n\n{}".format(admin_html)).encode()) # use .format instead of f-string
    elif method == "GET" and path_base == "/leaderboard_excel": # Use path_base here
        leaderboard = load_leaderboard()
        csv_data = generate_leaderboard_csv(leaderboard)
        conn.sendall(("HTTP/1.1 200 OK\nContent-Type: text/csv\nContent-Disposition: attachment; filename=\"leaderboard.csv\"\n\n{}".format(csv_data)).encode()) # use .format instead of f-string
    elif method == "POST" and path_base == "/add": # Use path_base here
        # Handle adding a new entry to the leaderboard - Expecting JSON data
        try:
            body_data = None
            for i, line in enumerate(request_lines):
                if line == "":
                    body_data = request_lines[i + 1]
                    break

            if body_data is None:
                raise ValueError("Body data not found in request")

            print("Received JSON data:", body_data)

            # Parse JSON data
            received_json = json.loads(body_data)
            print("Parsed JSON:", received_json)
            name = received_json.get("name")
            time_taken = received_json.get("time")
            answers_data = received_json.get("answers")
            category_uid_str = received_json.get("category_uid", None) # Get category UID from client
            category_name = get_category_name_from_uid_str(category_uid_str) if category_uid_str else "All Categories" # Determine category name

            if name is None or time_taken is None or answers_data is None:
                raise ValueError("Invalid JSON data: 'name', 'time', or 'answers' missing")

            add_to_leaderboard(name, time_taken, answers_data, category_name) # Pass category name to add_to_leaderboard
            conn.sendall(b"HTTP/1.1 200 OK\nContent-Type: text/plain\n\nEntry added!")

        except Exception as e:
            print("Error processing data:", e)
            conn.sendall(b"HTTP/1.1 400 Bad Request\nContent-Type: text/plain\n\nInvalid data format")
    elif method == "POST" and path_base == "/reset": # Legacy reset, will not be used now, but kept for compatibility if client sends to /reset # Use path_base here
        # Handle leaderboard reset request
        clear_leaderboard()
        conn.sendall(b"HTTP/1.1 200 OK\nContent-Type: text/plain\n\nLeaderboard reset!")
    elif method == "POST" and path_base == "/admin_reset": # Use path_base here
        # Handle leaderboard reset request from admin page with password
        post_data = {}
        body_data = None
        for i, line in enumerate(request_lines):
            if line == "":
                body_data = request_lines[i + 1]
                break
        if body_data:
            for param in body_data.split("&"):
                parts = param.split("=", 1)
                if len(parts) == 2:
                    key, value = parts
                    post_data[key] = value

        password_attempt = post_data.get("password")
        if password_attempt == ADMIN_PASSWORD:
            clear_leaderboard()
            conn.sendall(b"HTTP/1.1 200 OK\nContent-Type: text/html\n\n<html><head><style>.button-link { display: inline-block; padding: 12px 25px; background-color: #428bca; color: white; text-decoration: none; border-radius: 5px; font-size: 1em; transition: background-color 0.3s ease; }.button-link:hover { background-color: #3071a9; }</style></head><body><h1>Leaderboard Reset!</h1><div style='text-align: center; margin-top: 20px;'> <a href='/admin' class='button-link'>Back to Admin Page</a>  <a href='/' class='button-link'>Back to Leaderboard</a> </div></body></html>") # Made them buttons, added text-decoration: none;
        else:
            conn.sendall(b"HTTP/1.1 403 Forbidden\nContent-Type: text/plain\n\nIncorrect Admin Password")

    elif method == "POST" and path_base == "/save_answers": # Use path_base here
        # Handle saving correct answers and penalty
        try:
            post_data = {}
            body_data = None
            print("Entering POST /save_answers handler")
            for i, line in enumerate(request_lines):
                if line == "":
                    body_data = request_lines[i + 1]
                    break
            if body_data:
                print("Received body_data: '{}'".format(body_data)) # use .format instead of f-string
                # Parse form data (simple key-value pairs)
                for param in body_data.split("&"):
                    print("Processing param: '{}'".format(param)) # use .format instead of f-string
                    parts = param.split("=", 1)
                    if len(parts) == 2:
                        key, value = parts
                        post_data[key] = value
                        print("Parsed key: '{}', value: '{}'".format(key, value)) # use .format instead of f-string
                    else:
                        print("Warning: Skipping malformed form parameter: {}".format(param)) # use .format instead of f-string
            else:
                print("Warning: body_data is empty!")

            updated_correct_answers = {}
            for i in range(1, 16):
                question_num = str(i)
                answer = post_data.get("answer{}".format(i), "") # use .format instead of f-string
                if answer:
                    updated_correct_answers[question_num] = answer

            penalty_str = post_data.get("penalty", "10")
            try:
                updated_penalty = int(penalty_str)
            except ValueError:
                updated_penalty = 60

            # --- Update the config dictionary ---
            correct_answers_config
            correct_answers_config = {"penalty": updated_penalty, "answers": updated_correct_answers}

            # --- Update the global variables used elsewhere ---
            correct_answers
            PENALTY_PER_INCORRECT
            correct_answers = updated_correct_answers
            PENALTY_PER_INCORRECT = updated_penalty

            response_html = """<!DOCTYPE html>
<html><head><title>Settings Saved!</title><style>.button-link { display: inline-block; padding: 12px 25px; background-color: #428bca; color: white; text-decoration: none; border-radius: 5px; font-size: 1em; transition: background-color 0.3s ease; }.button-link:hover { background-color: #3071a9; }</style></head><body><h1>Settings Saved!</h1><div style='text-align: center; margin-top: 20px;'> <button onclick="window.location.href='/admin'" class='button-link'>Back to Admin Page</button>  <button onclick="window.location.href='/'" class='button-link'>Back to Leaderboard</button> </div></body></html>"""
            print("--- HTML Response being sent: ---") # DEBUG PRINT
            print(response_html) # DEBUG PRINT
            print("--- End of HTML Response ---") # DEBUG PRINT

            conn.sendall(("HTTP/1.1 200 OK\nContent-Type: text/html\n\n{}".format(response_html)).encode()) # use .format instead of f-string


        except Exception as e:
            print("Error saving settings:", e)
            conn.sendall(b"HTTP/1.1 400 Bad Request\nContent-Type: text/plain\n\nError saving settings")

    else:
        conn.sendall(b"HTTP/1.1 404 Not Found\nContent-Type: text/plain\n\nNot Found")

    conn.close()
