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
correct_answers_file = "correct_answers.json" # File to store correct answers and penalty

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
    default_config = {"penalty": 10, "answers": {}}  # Default config
    print("load_correct_answers_config: Starting to load config...") # DEBUG: Function entry

    try:
        print(f"load_correct_answers_config: Attempting to open file: '{correct_answers_file}'") # DEBUG: File open attempt
        with open(correct_answers_file, "r") as f:
            print("load_correct_answers_config: File opened successfully.") # DEBUG: File open success
            try:
                config = json.load(f)
                print("load_correct_answers_config: JSON loaded successfully. Content:", config) # DEBUG: JSON load success and content
                if isinstance(config, dict) and "penalty" in config and "answers" in config:
                    print("load_correct_answers_config: Config is valid, returning loaded config.") # DEBUG: Valid config
                    return config
                else:
                    print("load_correct_answers_config: Warning: Config file content is invalid structure. Using default.") # DEBUG: Invalid structure
                    return default_config
            except ValueError as json_err:
                print(f"load_correct_answers_config: ERROR: JSON Decode Error: {json_err}. Using default config.") # DEBUG: JSON error
                return default_config
    except OSError as os_err:
        if os_err.args[0] == 2: # FileNotFoundError (ENOENT)
            print(f"load_correct_answers_config: FileNotFoundError: {os_err}. Using default config.") # DEBUG: File not found
        else:
            print(f"load_correct_answers_config: OSError opening file: {os_err}. Using default config.") # DEBUG: Other OSError
        return default_config
    except Exception as general_err: # Catch-all for any other unexpected errors
        print(f"load_correct_answers_config: ERROR: Unexpected Exception: {general_err}. Using default config.") # DEBUG: General error
        return default_config
    else: # Added explicit else clause to the OUTER try block
        print("load_correct_answers_config: WARNING: Reached ELSE clause of outer try-except, should not happen. Returning default config as fallback.") # DEBUG: Should not reach here, but logging if it does
        return default_config # Fallback return from ELSE, even more robust

    print("load_correct_answers_config: WARNING: Reached end of function unexpectedly, should not happen. Returning default config as fallback.") # DEBUG: Should not reach here
    return default_config # Fallback return, should GUARANTEE a dictionary is returned

def save_correct_answers_config(config):
    """Saves correct answers and penalty config to a JSON file."""
    try:
        with open(correct_answers_file, "w") as f:
            json.dump(config, f)
        print("Correct answers and penalty config saved to file.")
    except Exception as e:
        print(f"Error saving correct answers and penalty config to file: {e}")

correct_answers_config = load_correct_answers_config() # Load config at startup
correct_answers = correct_answers_config["answers"] # Extract answers
PENALTY_PER_INCORRECT = correct_answers_config["penalty"] # Extract penalty

def add_to_leaderboard(name, time_taken, answers):
    """Adds a new entry to the leaderboard, calculates penalty, and sorts it."""
    leaderboard = load_leaderboard()
    correct_answers_config = load_correct_answers_config() # Reload config to get latest answers
    correct_answers = correct_answers_config["answers"] # Extract answers
    PENALTY_PER_INCORRECT = correct_answers_config["penalty"] # Extract penalty

    penalty_seconds = 0
    incorrect_answers_count = 0
    unanswered_questions_count = 0 # Counter for unanswered questions

    # Determine the number of questions from the correct_answers config
    num_questions = len(correct_answers) if correct_answers else 15 # Default to 15 if no config loaded yet

    for question_num in range(1, num_questions + 1): # Iterate through expected question numbers
        question_num_str = str(question_num)
        submitted_answer = answers.get(question_num_str) # Get submitted answer, might be None

        if submitted_answer is None: # Question was not answered
            penalty_seconds += PENALTY_PER_INCORRECT
            unanswered_questions_count += 1
            print(f"Question {question_num} unanswered - Penalty applied.") # Feedback for unanswered questions
        else: # Question was answered, check if correct
            correct_answer = correct_answers.get(question_num_str)
            if correct_answer and submitted_answer != correct_answer:
                penalty_seconds += PENALTY_PER_INCORRECT
                incorrect_answers_count += 1

    penalized_time = time_taken + penalty_seconds
    print(f"Incorrect answers: {incorrect_answers_count}, Unanswered questions: {unanswered_questions_count}, Penalty: {penalty_seconds} seconds") # Include unanswered count in print
    print(f"Penalized Time: {penalized_time} seconds")

    leaderboard.append({"name": name, "time": penalized_time, "penalty": penalty_seconds}) # Store penalty
    leaderboard.sort(key=lambda x: x["time"])
    save_leaderboard(leaderboard)
    print(f"Added to leaderboard: Name={name}, Time={penalized_time} (Penalized)")

def clear_leaderboard():
    """Clears all entries from the leaderboard."""
    save_leaderboard([])
    print("Leaderboard cleared.")

# --- HTML for Webpages ---
def generate_leaderboard_html(leaderboard):
    """Generates the HTML content for the leaderboard webpage."""
    html = ""
    html += """
    <!DOCTYPE html>
    <html>
    <head>
        <title>ESP32 Leaderboard</title>
        <style>
            body { font-family: sans-serif; }
            table { border-collapse: collapse; width: 450px; margin: 20px auto; } /* Wider table */
            th, td { border: border-collapse: collapse; width: 450px; margin: 20px auto; } /* Wider table */
            th, td { border: 1px solid black; padding: 8px; text-align: left; }
            .button-link { display: inline-block; padding: 10px 20px; background-color: #4CAF50; color: white; text-decoration: none; border-radius: 5px; } /* Button style */
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

            function resetLeaderboard() {
                var xhttp = new XMLHttpRequest();
                xhttp.onreadystatechange = function() {
                    if (this.readyState == 4 && this.status == 200) {
                        refreshLeaderboard();
                    }
                };
                xhttp.open("POST", "/reset", true);
                xhttp.send();
            }

            setInterval(refreshLeaderboard, 5000);
        </script>
    </head>
    <body>
        <h1>ESP32 Leaderboard</h1>
        <a href="/admin" class="button-link">Admin Page</a> <button onclick="resetLeaderboard()">Reset Leaderboard</button> <br><br>
        <div id="leaderboard">
            """
    html += generate_leaderboard_table_html(leaderboard)
    html += """
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
                <th>Time (s)</th>
                <th>Penalty (s)</th>
                <th>Final Time (s)</th>
            </tr>
        </thead>
        <tbody>
            """
    for i, entry in enumerate(leaderboard):
        penalty = entry.get('penalty', 0)
        final_time = entry['time']
        original_time = final_time - penalty if penalty > 0 else final_time

        table_html += f"""
            <tr>
                <td>{i + 1}</td>
                <td>{entry['name']}</td>
                <td>{original_time:.2f}</td>
                <td>{penalty:.2f}</td>
                <td>{final_time:.2f}</td>
            </tr>
            """
    table_html += """
        </tbody>
    </table>
    """
    return table_html

def generate_admin_html(config): # Pass whole config
    """Generates the HTML for the admin page to set correct answers and penalty."""
    penalty = config.get("penalty", 10) # Default penalty if not set
    current_correct_answers = config.get("answers", {}) # Default empty answers if not set

    html = ""
    html += """
    <!DOCTYPE html>
    <html>
    <head>
        <title>ESP32 Admin - Set Correct Answers and Penalty</title>
        <style> /* ADDED STYLE BLOCK HERE */
            body {{ font-family: sans-serif; }}
            .container {{ width: 400px; margin: 20px auto; }}
            label {{ display: block; margin-top: 10px; }}
            input[type="text"], select {{ width: 100%; padding: 8px; margin-top: 5px; margin-bottom: 10px; box-sizing: border-box; }}
            button, .button-link {{ display: inline-block; padding: 10px 20px; background-color: #4CAF50; color: white; text-decoration: none; border-radius: 5px; border: none; cursor: pointer; }}
            .button-link {{ background-color: #008CBA; }} /* Different color for back link */
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Admin - Correct Answers and Penalty</h1>
            <a href="/" class="button-link">Back to Leaderboard</a> <br><br>
            <form action="/save_answers" method="post">
                <label for="penalty">Penalty per Incorrect Answer (seconds):</label>
                <input type="number" id="penalty" name="penalty" value="{}" required>
                """.format(penalty) # Input for penalty
    for i in range(1, 16): # Assuming 15 questions, adjust if needed
        question_num = str(i)
        current_answer = current_correct_answers.get(question_num, "") # Get current answer or default to empty
        html += f"""
                <label for="answer{i}">Question {i}:</label>
                <select id="answer{i}" name="answer{i}">
                    <option value="A" {'selected' if current_answer == 'A' else ''}>A</option>
                    <option value="B" {'selected' if current_answer == 'B' else ''}>B</option>
                    <option value="C" {'selected' if current_answer == 'C' else ''}>C</option>
                    <option value="D" {'selected' if current_answer == 'D' else ''}>D</option>
                    <option value=""  {'selected' if current_answer == '' else ''}>Not Set</option>
                </select>
                """
    html += """
                <button type="submit">Save Settings</button>
            </form>
        </div>
    </body>
    </html>
    """
    return html


# --- Socket Server ---
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(('', 80))
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
        admin_html = generate_admin_html(correct_answers_config) # Pass whole config
        conn.sendall(f"HTTP/1.1 200 OK\nContent-Type: text/html\n\n{admin_html}".encode())
    elif method == "POST" and path == "/add":
        # Handle adding a new entry to the leaderboard - Expecting JSON data
        try:
            body_data = None
            for i, line in enumerate(request_lines):
                if line == '':
                    body_data = request_lines[i + 1]
                    break

            if body_data is None:
                raise ValueError("Body data not found in request")

            print("Received JSON data:", body_data) # Debug print - Log the received JSON

            # Parse JSON data
            received_json = json.loads(body_data)
            print("Parsed JSON:", received_json) # Debug print - Log parsed JSON
            name = received_json.get("name")
            time_taken = received_json.get("time")
            answers_data = received_json.get("answers") # Get answers data

            if name is None or time_taken is None or answers_data is None: # Check for answers_data too
                raise ValueError("Invalid JSON data: 'name', 'time', or 'answers' missing")

            add_to_leaderboard(name, time_taken, answers_data) # Pass answers to add_to_leaderboard
            conn.sendall(b"HTTP/1.1 200 OK\nContent-Type: text/plain\n\nEntry added!")

        except Exception as e:
            print("Error processing data:", e)
            conn.sendall(b"HTTP/1.1 400 Bad Request\nContent-Type: text/plain\n\nInvalid data format")
    elif method == "POST" and path == "/reset":
        # Handle leaderboard reset request
        clear_leaderboard()
        conn.sendall(b"HTTP/1.1 200 OK\nContent-Type: text/plain\n\nLeaderboard reset!")
    elif method == "POST" and path == "/save_answers": # Handle saving correct answers and penalty
        try:
            post_data = {}
            body_data = None
            print("Entering POST /save_answers handler") # Debug entry
            for i, line in enumerate(request_lines):
                if line == '':
                    body_data = request_lines[i + 1]
                    break
            if body_data:
                print(f"Received body_data: '{body_data}'") # Debug log body_data
                # Parse form data (simple key-value pairs)
                for param in body_data.split('&'):
                    print(f"Processing param: '{param}'") # Debug log param
                    parts = param.split('=', 1)
                    if len(parts) == 2:
                        key, value = parts
                        post_data[key] = value
                        print(f"Parsed key: '{key}', value: '{value}'") # Debug log key-value
                    else:
                        print(f"Warning: Skipping malformed form parameter: {param}") # Log warning for malformed param
            else:
                print("Warning: body_data is empty!") # Debug log empty body_data


            updated_correct_answers = {}
            for i in range(1, 16): # Assuming 15 questions, adjust if needed
                question_num = str(i)
                answer = post_data.get(f"answer{i}", "") # Get answer from form data
                if answer: # Only save if an answer is selected
                    updated_correct_answers[question_num] = answer

            penalty_str = post_data.get("penalty", "10") # Get penalty from form, default to 10
            try:
                updated_penalty = int(penalty_str) # Convert penalty to integer
            except ValueError:
                updated_penalty = 10 # Default penalty if conversion fails

            updated_config = {"penalty": updated_penalty, "answers": updated_correct_answers} # Create updated config

            save_correct_answers_config(updated_config) # Save whole config to file
            correct_answers_config = updated_config
            correct_answers # Update global correct_answers and penalty
            correct_answers = updated_correct_answers
            PENALTY_PER_INCORRECT
            PENALTY_PER_INCORRECT = updated_penalty


            conn.sendall(b"HTTP/1.1 200 OK\nContent-Type: text/html\n\n<html><body><h1>Settings Saved!</h1><p><a href='/admin'>Back to Admin Page</a> | <a href='/'>Back to Leaderboard</a></p></body></html>") # Confirmation page with link to leaderboard

        except Exception as e:
            print("Error saving settings:", e)
            conn.sendall(b"HTTP/1.1 400 Bad Request\nContent-Type: text/plain\n\nError saving settings")

    else:
        conn.sendall(b"HTTP/1.1 404 Not Found\nContent-Type: text/plain\n\nNot Found")

    conn.close()