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
        print(f"Error saving leaderboard to file: {e}")

def load_correct_answers_config():
    """Loads correct answers and penalty config from a JSON file."""
    default_config = {"penalty": 10, "answers": {}}
    print("load_correct_answers_config: Starting to load config...")

    try:
        print(f"load_correct_answers_config: Attempting to open file: '{correct_answers_file}'")
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
                print(f"load_correct_answers_config: ERROR: JSON Decode Error: {json_err}. Using default config.")
                return default_config
    except OSError as os_err:
        if os_err.args[0] == 2:
            print(f"load_correct_answers_config: FileNotFoundError: {os_err}. Using default config.")
        else:
            print(f"load_correct_answers_config: OSError opening file: {os_err}. Using default config.")
        return default_config
    except Exception as general_err:
        print(f"load_correct_answers_config: ERROR: Unexpected Exception: {general_err}. Using default config.")
        return default_config
    else:
        print("load_correct_answers_config: WARNING: Reached ELSE clause of outer try-except, should not happen. Returning default config as fallback.")
        return default_config

    print("load_correct_answers_config: WARNING: Reached end of function unexpectedly, should not happen. Returning default config as fallback.")
    return default_config

def save_correct_answers_config(config):
    """Saves correct answers and penalty config to a JSON file."""
    try:
        with open(correct_answers_file, "w") as f:
            json.dump(config, f)
        print("Correct answers and penalty config saved to file.")
    except Exception as e:
        print(f"Error saving correct answers and penalty config to file: {e}")

correct_answers_config = load_correct_answers_config()
correct_answers = correct_answers_config["answers"]
PENALTY_PER_INCORRECT = correct_answers_config["penalty"]

def add_to_leaderboard(name, time_taken, answers):
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
            print(f"Question {question_num} unanswered - Penalty applied.")
        else:
            correct_answer = correct_answers.get(question_num_str)
            if correct_answer and submitted_answer != correct_answer:
                penalty_seconds += PENALTY_PER_INCORRECT
                incorrect_answers_count += 1

    penalized_time = time_taken + penalty_seconds
    print(f"Incorrect answers: {incorrect_answers_count}, Unanswered questions: {unanswered_questions_count}, Penalty: {penalty_seconds} seconds")
    print(f"Penalized Time: {penalized_time} seconds")

    leaderboard.append({"name": name, "time": penalized_time, "penalty": penalty_seconds})
    leaderboard.sort(key=lambda x: x["time"])
    save_leaderboard(leaderboard)
    print(f"Added to leaderboard: Name={name}, Time={penalized_time} (Penalized)")

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

# --- HTML for Webpages ---
def generate_leaderboard_html(leaderboard):
    """Generates the HTML content for the leaderboard webpage."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>ESP32 Leaderboard</title>
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
            .button-link2 { display: inline-block; padding: 12px 25px; background-color: #5bc0de; color: white; text-decoration: none; border-radius: 5px; font-size: 1em; transition: background-color 0.3s ease; }
            .button-link2:hover { background-color: #31b0d5; }
            .reset-button { display: inline-block; padding: 12px 25px; background-color: #d9534f; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 1em; transition: background-color 0.3s ease; text-decoration: none;}
            .reset-button:hover { background-color: #c9302c; }
            table { border-collapse: collapse; width: 80%; max-width: 800px; margin: 20px auto; }
            th, td { border: 1px solid black; padding: 8px; text-align: left; }

        </style>
        <script>
            function refreshLeaderboard() {
                var xhttp = new XMLHttpRequest();
                xhttp.onreadystatechange = function() {
                    if (this.readyState == 4 && this.status == 200) {
                        document.getElementById("leaderboard").innerHTML = this.responseText;
                    }
                };
                xhttp.open("GET", "/leaderboard_table", true);
                xhttp.send();
            }
        </script>
    </head>
    <body>
        <div class="header-buttons">
            <a href="/admin" class="button-link" style="background-color: green;">Admin Page</a>
        </div>
        <div class="container">
            <h1>ESP32 Leaderboard</h1>
            <div id="leaderboard">
                """
    html += generate_leaderboard_table_html(leaderboard)
    html += """
            </div>
        </div>
    </body>
    </html>
    """
    return html

def generate_leaderboard_table_html(leaderboard):
    """Generates the HTML for the leaderboard table."""
    table_html = """
    <table>
        <thead>
            <tr>
                <th>Rank</th>
                <th>Name</th>
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

        table_html += f"""
            <tr>
                <td>{i + 1}</td>
                <td>{entry['name']}</td>
                <td>{format_time(original_time_sec)}</td>
                <td>{format_time(penalty_sec)}</td>
                <td>{format_time(final_time_sec)}</td>
            </tr>
            """
    table_html += """
        </tbody>
    </table>
    """
    return table_html

def generate_admin_html(config):
    """Generates the HTML for the admin page to set correct answers and penalty."""
    penalty = config.get("penalty", 10)
    current_correct_answers = config.get("answers", {})

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>ESP32 Admin - Set Correct Answers and Penalty</title>
        <style>
            body { font-family: Arial, sans-serif; background-color: #f4f4f4; color: #333; margin: 0; padding: 20px; }
            .container { width: 80%; max-width: 800px; margin: 20px auto; background-color: white; padding: 30px; border-radius: 10px; box-shadow: 0 0 20px rgba(0, 0, 0, 0.1); }
            h1 { text-align: center; color: #4472C4; }
            h2 { color: #4472C4; margin-top: 25px; border-bottom: 1px solid #eee; padding-bottom: 5px; }
            label { display: block; margin-top: 15px; font-weight: bold; }
            input[type="number"], select, input[type="password"] { width: calc(100% - 20px); padding: 10px; margin-top: 8px; margin-bottom: 15px; border: 1px solid #ddd; border-radius: 5px; box-sizing: border-box; font-size: 1em; }
            select { appearance: none; -webkit-appearance: none; -moz-appearance: none; background-image: url('data:image/svg+xml;utf8,<svg fill="black" height="24" viewBox="0 0 24 24" width="24" xmlns="http://www.w3.org/2000/svg"><path d="M7 10l5 5 5-5z"/><path d="M0 0h24v24H0z" fill="none"/></svg>'); background-repeat: no-repeat; background-position-x: 100%; background-position-y: 5px; } /* Custom arrow for select */
            button, .button-link, .button-link2, .reset-button { display: inline-block; padding: 12px 25px; background-color: #5cb85c; color: white; text-decoration: none; border-radius: 5px; border: none; cursor: pointer; font-size: 1em; transition: background-color 0.3s ease; margin-top: 10px; }
            button:hover, .button-link:hover, .button-link2:hover, .reset-button:hover { background-color: #4cae4c; }
            .button-link { background-color: #428bca; }
            .button-link:hover { background-color: #3071a9; }
            .button-link2 { background-color: #5bc0de; color: white; } /* Example different button */
            .button-link2:hover { background-color: #31b0d5; }
            .reset-button { background-color: #d9534f; }
            .reset-button:hover { background-color: #c9302c; }
            .button-container, .button-container2, .reset-button-container { text-align: center; margin-top: 20px; }
            .button-link, .button-link2 { width: auto; display: block; margin: 15px auto; max-width: 200px; } /* Button links as blocks */
            .reset-section { margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; }
            .form-group { margin-bottom: 20px; }
            .form-group:last-child { margin-bottom: 0; }

        </style>
        <script>
            function checkPasswordAndReset() {
                var password = document.getElementById('resetPassword').value;
                if (password === '""" + ADMIN_PASSWORD + """') {
                    if (confirm('Are you sure you want to reset the leaderboard? This action cannot be undone.')) {
                        var xhr = new XMLHttpRequest();
                        xhr.open('POST', '/admin_reset', true);
                        xhr.setRequestHeader('Content-type', 'application/x-www-form-urlencoded');
                        xhr.onload = function () {
                            if (xhr.status == 200) {
                                alert('Leaderboard reset successfully!');
                                window.location.href = '/admin'; // Refresh admin page to show empty leaderboard
                            } else {
                                alert('Error resetting leaderboard.');
                            }
                        };
                        xhr.send('password=' + password);
                    }
                } else {
                    alert('Incorrect password. Reset aborted.');
                }
            }
        </script>
    </head>
    <body>
        <div class="container">
            <h1>Admin - Correct Answers and Penalty</h1>
            <form action="/save_answers" method="post">
                <div class="form-group">
                    <label for="penalty">Penalty per Incorrect Answer (seconds):</label>
                    <input type="number" id="penalty" name="penalty" value="{str(penalty)}" required>
                </div>"""
    for i in range(1, 16):
        question_num = str(i)
        current_answer = current_correct_answers.get(question_num, "")

        option_a_selected = 'selected' if current_answer == 'A' else ''
        option_b_selected = 'selected' if current_answer == 'B' else ''
        option_c_selected = 'selected' if current_answer == 'C' else ''
        option_d_selected = 'selected' if current_answer == 'D' else ''
        option_empty_selected = 'selected' if current_answer == '' else ''


        html += f"""
                <div class="form-group">
                    <label for="answer{i}">Question {i}:</label>
                    <select id="answer{i}" name="answer{i}">
                        <option value="A" {option_a_selected}>A</option>
                        <option value="B" {option_b_selected}>B</option>
                        <option value="C" {option_c_selected}>C</option>
                        <option value="D" {option_d_selected}>D</option>
                        <option value=""  {option_empty_selected}>Not Set</option>
                    </select>
                </div>"""
    html += """
                <div class="button-container">
                    <button type="submit" class="button-link2" >Save Settings</button>
                </div>
            </form>

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
    method, path, _ = request_line.split(" ")

    if method == "GET" and path == "/":
        leaderboard = load_leaderboard()
        html = generate_leaderboard_html(leaderboard)
        conn.sendall(f"HTTP/1.1 200 OK\nContent-Type: text/html\n\n{html}".encode())
    elif method == "GET" and path == "/leaderboard_table":
        leaderboard = load_leaderboard()
        table_html = generate_leaderboard_table_html(leaderboard)
        conn.sendall(f"HTTP/1.1 200 OK\nContent-Type: text/html\n\n{table_html}".encode())
    elif method == "GET" and path == "/admin":
        admin_html = generate_admin_html(correct_answers_config)
        conn.sendall(f"HTTP/1.1 200 OK\nContent-Type: text/html\n\n{admin_html}".encode())
    elif method == "POST" and path == "/add":
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

            if name is None or time_taken is None or answers_data is None:
                raise ValueError("Invalid JSON data: 'name', 'time', or 'answers' missing")

            add_to_leaderboard(name, time_taken, answers_data)
            conn.sendall(b"HTTP/1.1 200 OK\nContent-Type: text/plain\n\nEntry added!")

        except Exception as e:
            print("Error processing data:", e)
            conn.sendall(b"HTTP/1.1 400 Bad Request\nContent-Type: text/plain\n\nInvalid data format")
    elif method == "POST" and path == "/reset": # Legacy reset, will not be used now, but kept for compatibility if client sends to /reset
        # Handle leaderboard reset request
        clear_leaderboard()
        conn.sendall(b"HTTP/1.1 200 OK\nContent-Type: text/plain\n\nLeaderboard reset!")
    elif method == "POST" and path == "/admin_reset":
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
            conn.sendall(b"HTTP/1.1 200 OK\nContent-Type: text/html\n\n<html><body><h1>Leaderboard Reset!</h1><div style='text-align: center; margin-top: 20px;'> <a href='/admin' style='display: inline-block; padding: 10px 20px; background-color: #008CBA; color: white; text-decoration: none; border-radius: 5px; border: none; cursor: pointer; font-size: 1em; margin-right: 10px;'>Back to Admin Page</a>  <a href='/' style='display: inline-block; padding: 10px 20px; background-color: #4CAF50; color: white; text-decoration: none; border-radius: 5px; border: none; cursor: pointer; font-size: 1em;'>Back to Leaderboard</a> </div></body></html>")
        else:
            conn.sendall(b"HTTP/1.1 403 Forbidden\nContent-Type: text/plain\n\nIncorrect Admin Password")

    elif method == "POST" and path == "/save_answers":
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
                print(f"Received body_data: '{body_data}'")
                # Parse form data (simple key-value pairs)
                for param in body_data.split("&"):
                    print(f"Processing param: '{param}'")
                    parts = param.split("=", 1)
                    if len(parts) == 2:
                        key, value = parts
                        post_data[key] = value
                        print(f"Parsed key: '{key}', value: '{value}'")
                    else:
                        print(f"Warning: Skipping malformed form parameter: {param}")
            else:
                print("Warning: body_data is empty!")

            updated_correct_answers = {}
            for i in range(1, 16):
                question_num = str(i)
                answer = post_data.get(f"answer{i}", "")
                if answer:
                    updated_correct_answers[question_num] = answer

            penalty_str = post_data.get("penalty", "10")
            try:
                updated_penalty = int(penalty_str)
            except ValueError:
                updated_penalty = 10

            # --- Update the config dictionary ---
            correct_answers_config
            correct_answers_config = {"penalty": updated_penalty, "answers": updated_correct_answers}

            # --- Update the global variables used elsewhere ---
            correct_answers
            PENALTY_PER_INCORRECT
            correct_answers = updated_correct_answers
            PENALTY_PER_INCORRECT = updated_penalty

            # --- Save to file ---
            save_correct_answers_config(correct_answers_config)

            conn.sendall(
                b"HTTP/1.1 200 OK\nContent-Type: text/html\n\n<html><body><h1>Settings Saved!</h1><div style='text-align: center; margin-top: 20px;'> <a href='/admin' style='display: inline-block; padding: 10px 20px; background-color: #008CBA; color: white; text-decoration: none; border-radius: 5px; border: none; cursor: pointer; font-size: 1em; margin-right: 10px;'>Back to Admin Page</a>  <a href='/' style='display: inline-block; padding: 10px 20px; background-color: #4CAF50; color: white; text-decoration: none; border-radius: 5px; border: none; cursor: pointer; font-size: 1em;'>Back to Leaderboard</a> </div></body></html>"
            )

        except Exception as e:
            print("Error saving settings:", e)
            conn.sendall(b"HTTP/1.1 400 Bad Request\nContent-Type: text/plain\n\nError saving settings")

    else:
        conn.sendall(b"HTTP/1.1 404 Not Found\nContent-Type: text/plain\n\nNot Found")

    conn.close()
