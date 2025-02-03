import network
import usocket as socket
import time
import machine
from machine import Pin, SPI
import os
import mfrc522
import sdcard
import json  # Import the json library

# --- Wi-Fi Connection Details ---
ssid = "MyESP32S3AP"  # IMPORTANT: Match the SSID from your server.py
password = "yourpassword" # IMPORTANT: Match the password from your server.py
server_ip = "192.168.4.1" # IMPORTANT: Change this to the IP address printed by your server.py
server_port = 80

# ----- SPI Pin Configurations -----
# SD Card SPI (HSPI Pins)
sck_sd = 14  # HSPI SCK
mosi_sd = 13  # HSPI MOSI
miso_sd = 12  # HSPI MISO
cs_sd = 2  # SD Card CS

# RFID SPI (VSPI Pins)
sck_rfid = 18
mosi_rfid = 23
miso_rfid = 19
rst_rfid = 22
cs_rfid = 5

# LED Pins
led1_pin = Pin(33, Pin.OUT)  # LED for general feedback
led2_pin = Pin(32, Pin.OUT)  # LED for selection (if different from led1)
led1_pin.value(0)
led2_pin.value(0)

# Button Pins (with internal pull-ups)
button_a_pin = Pin(15, Pin.IN, Pin.PULL_UP)
button_b_pin = Pin(21, Pin.IN, Pin.PULL_UP)
button_c_pin = Pin(26, Pin.IN, Pin.PULL_UP)
button_d_pin = Pin(27, Pin.IN, Pin.PULL_UP)
button_confirm_pin = Pin(16, Pin.IN, Pin.PULL_UP)

# ----- SPI Bus Instances -----
# SD Card SPI (HSPI)
spi_sd = SPI(1, baudrate=1000000, polarity=0, phase=0, sck=Pin(sck_sd), mosi=Pin(mosi_sd), miso=Pin(miso_sd))

# RFID SPI (VSPI) - No need to initialize here, as mfrc522.py does it internally

# ----- Device Instantiation -----
# SD Card
sd = sdcard.SDCard(spi_sd, Pin(cs_sd))
# Mount filesystem
vfs = os.VfsFat(sd)
os.mount(vfs, "/sd")

# RFID Reader
reader = mfrc522.MFRC522(sck=sck_rfid, mosi=mosi_rfid, miso=miso_rfid, rst=rst_rfid, cs=cs_rfid)

# ----- Target RFID UIDs -----
START_UID = [0xF3, 0xC7, 0x1A, 0x13, 0x3D]  # Start tag UID
STOP_TIMER_UID = [0x00, 0x64, 0x56, 0xD3, 0xE1]  # Stop Timer tag UID - New UID for stopping timer only
WIFI_SEND_DATA_UID = [0xD3, 0x34, 0xE7, 0x11, 0x11] # UID to trigger Wi-Fi connection and data send - New UID for Wi-Fi and Send
QUESTIONS = {  # Use a dictionary to map UIDs to question numbers
    "0x730xED0xBF0x2C0x0D": 1,
    "0x230xBA0xCB0x2C0x7E": 2,
    "0x230xB80x9F0x2C0x28": 3,
    "0xD30x910xBF0x2C0xD1": 4,
    "0x730x2A0xD00x2C0xA5": 5,
    "0x830xED0xCF0x2C0x8D": 6,
    "0xB30x970xB40x2C0xBC": 7,
    "0xE30x110xBF0x2C0x61": 8,
    "0xD30x6E0xCE0x2C0x5F": 9,
    "0xB30xAA0xCD0x2C0xF8": 10,
    "0xC30xE40xB90x2C0xB2": 11,
    "0x530xB30xCD0x2C0x01": 12,
    "0x830x740xF80x2C0x23": 13,
    "0xE30xD40xCB0x2C0xD0": 14,
    "0x130xE90xA00x2C0x76": 15
}

# ----- State Variables -----
current_question = 0
selected_answer = None
timer_running = False
timer_start_time = 0
elapsed_time = 0
timer_stopped = False
answers = {}  # Dictionary to store selected answers: {question_num: answer}

# ----- Helper Functions -----
def byte_array_to_str(byte_arr):
    """Converts a byte array to a byte array to a hex string (e.g., [0x12, 0xAB] -> "0x120xAB")."""
    return "".join(["0x{:02X}".format(x) for x in byte_arr])

def save_time_to_sdcard(elapsed_time):
    """Saves the elapsed time to the timer_log.txt file on the SD card."""
    try:
        with open("/sd/timer_log.txt", "w") as f:
            f.write(f"Time: {elapsed_time} seconds\n")
            print("Time saved to SD card")
    except Exception as e:
        print(f"Error saving to SD card: {e}")

def read_time_from_sdcard():
    """Reads the elapsed time from the timer_log.txt file on the SD card."""
    try:
        with open("/sd/timer_log.txt", "r") as f:
            time_str = f.readline().split(":")[1].strip().split(" ")[0]  # Extract time value
            return float(time_str)
    except Exception as e:
        print(f"Error reading time from SD card: {e}")
        return None # Or raise the exception, depending on desired behavior

def read_answers_from_sdcard():
    """Reads answers from the answers.txt file on the SD card."""
    answers = {}
    try:
        with open("/sd/answers.txt", "r") as f:
            for line in f:
                parts = line.strip().split(":")
                if len(parts) == 2:
                    question_num = int(parts[0])
                    answer = parts[1].strip()
                    answers[question_num] = answer
    except Exception as e:
        print(f"Error reading answers from SD card: {e}")
    return answers

def save_answer_to_sdcard(question_num, answer):
    """Saves the selected answer for a question to the answers.txt file."""
    global answers
    try:
        answers[question_num] = answer
        with open("/sd/answers.txt", "a") as f:
            f.write(f"{question_num}: {answer}\n")
            print(f"Question {question_num} - Answer saved to SD card")
    except Exception as e:
        print(f"Error saving to SD card: {e}")

def create_empty_answers_file():
    """Creates an empty answers.txt file on the SD card."""
    try:
        with open("/sd/answers.txt", "w") as f:
            print("Empty answers file created on the SD card")
    except Exception as e:
        print(f"Error creating answers file on SD card: {e}")

def delete_answer_time_files():
    """Deletes answers.txt and timer_log.txt files from the SD card."""
    files_to_delete = ["/sd/answers.txt", "/sd/timer_log.txt"]
    for file_path in files_to_delete:
        try:
            os.remove(file_path)
            print(f"Deleted file: {file_path}")
        except OSError as e:
            if e.args[0] == 2:  # FileNotFoundError
                print(f"File not found, skipping deletion: {file_path}")
            else:
                print(f"Error deleting file {file_path}: {e}")


# --- Function to Send Data to Server ---
def send_data(name, sta): # Pass sta object
    retries = 3
    retry_delay = 1

    elapsed_time_from_sd = read_time_from_sdcard() # Read time from SD card
    answers_from_sd = read_answers_from_sdcard()    # Read answers from SD card

    if elapsed_time_from_sd is None:
        print("Could not read time from SD card. Aborting send.")
        return False

    data_payload = { # Create JSON payload
        "name": name,
        "time": elapsed_time_from_sd,
        "answers": answers_from_sd # Include answers in payload
    }
    json_data = json.dumps(data_payload) # Convert to JSON string
    print("JSON Payload to send:", json_data) # Debug print JSON data

    for attempt in range(retries):
        try:
            print(f"Attempting to connect to server: {server_ip}:{server_port} (Attempt {attempt+1}/{retries})") # Debug connect attempt
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5) # Set timeout for connection and receiving
            s.connect((server_ip, server_port))
            print("Connected to server.") # Debug connection success

            request = f"POST /add HTTP/1.1\r\nHost: {server_ip}\r\nContent-Type: application/json\r\nContent-Length: {len(json_data)}\r\n\r\n{json_data}" # Content-Type: application/json
            print("Sending HTTP Request:\n", request) # Debug print HTTP request

            s.sendall(request.encode())
            print("Request sent.") # Debug request send

            response = s.recv(1024)
            print("Server Response:", response.decode()) # Debug server response

            s.close()
            print("Socket closed.") # Debug socket close
            return True

        except Exception as e:
            print(f"Error sending data (attempt {attempt+1}/{retries}): {e}") # Keep original error print
            if attempt < retries - 1:
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                print("Max retries reached. Giving up.")
                return False
        finally:
            if sta.isconnected(): # Only disconnect if still connected
                print("Disconnecting from Wi-Fi...")
                sta.disconnect()
                while sta.isconnected():
                    print("Waiting for Wi-Fi disconnect...")
                    time.sleep(0.5)
                print("Disconnected from Wi-Fi")
            else:
                print("Wi-Fi already disconnected or not connected.")


def handle_start_card(uid_str):
    """Handles the START card logic."""
    global timer_running, timer_stopped, timer_start_time, current_question, answers
    if timer_running:
        timer_running = False
        timer_stopped = True
        print("Resetting...")
    timer_start_time = time.ticks_ms()
    timer_running = True
    timer_stopped = False
    current_question = 0
    answers = {}
    print("Project Reset - Timer Started")
    delete_answer_time_files() # Delete answers.txt and timer_log.txt
    create_empty_answers_file() # Create a new empty answers.txt
    led1_pin.value(1)
    time.sleep(1)
    led1_pin.value(0)
    led2_pin.value(0)

def handle_stop_card(uid_str, uid_bytes):
    """Handles the STOP card logic (only stops timer)."""
    global timer_running, timer_stopped, elapsed_time

    if timer_running and not timer_stopped:
        elapsed_time = (time.ticks_ms() - timer_start_time) // 1000
        timer_running = False
        timer_stopped = True
        print("Timer Stopped, Elapsed Time:", elapsed_time)
        for _ in range(2):
            led1_pin.value(1)
            time.sleep(0.5)
            led1_pin.value(0)
            time.sleep(0.5)
        save_time_to_sdcard(elapsed_time)

        answers = read_answers_from_sdcard()
        print("Data saved to SD card.")
    else:
        print("Timer is not running or already stopped.")

def handle_wifi_send_card(uid_str, uid_bytes):
    """Handles the Wi-Fi connect and send data card logic."""
    global timer_stopped

    if timer_stopped: # Only connect if timer is stopped
        print("Connecting to Wi-Fi and Sending Data...")
        time.sleep(1) # Keep a small delay before Wi-Fi connection

        # --- Connect to Wi-Fi (Only when WIFI_SEND_DATA_UID card is scanned) ---
        sta = network.WLAN(network.STA_IF) # Create sta object here
        sta.active(True)
        print(f"Attempting to connect to Wi-Fi SSID: '{ssid}'") # Debug SSID
        sta.connect(ssid, password)

        wifi_connect_timeout = time.time() + 10 # 10 seconds timeout for Wi-Fi connection
        while not sta.isconnected() and time.time() < wifi_connect_timeout:
            print("Connecting to Wi-Fi...")
            time.sleep(1)

        if sta.isconnected():
            print("Connected to Wi-Fi. IP:", sta.ifconfig()[0])
            rssi = sta.status('rssi') # Get RSSI
            print(f"Wi-Fi RSSI: {rssi} dBm") # Print RSSI

            # --- Send Data to Server ---
            if send_data("Client1", sta): # Call send_data, no time argument needed
                print("Data sent to server successfully.")
                led1_pin.value(1) # Indicate success with LED
                time.sleep(2)
                led1_pin.value(0)
            else:
                print("Failed to send data after multiple retries.")
                led1_pin.value(0) # Indicate failure with LED off
                led2_pin.value(1) # Maybe a different LED for failure?
                time.sleep(2)
                led2_pin.value(0)

        else:
            print("Wi-Fi connection timed out. Check SSID/password and Wi-Fi AP.")
            led2_pin.value(1) # Indicate Wi-Fi failure
            time.sleep(2)
            led2_pin.value(0)

    else:
        print("Timer is not stopped. Stop timer first to send data.")


def handle_question_card(uid_str, question_num):
    """Handles question card logic."""
    global selected_answer
    if timer_running and question_num not in answers:
        print(f"Question {question_num} active")
        led2_pin.value(1)
        selected_answer = None

        while button_confirm_pin.value() != 0:
            if button_a_pin.value() == 0:
                selected_answer = "A"
                print("Option A selected")
                time.sleep(0.2)
            elif button_b_pin.value() == 0:
                selected_answer = "B"
                print("Option B selected")
                time.sleep(0.2)
            elif button_c_pin.value() == 0:
                selected_answer = "C"
                print("Option C selected")
                time.sleep(0.2)
            elif button_d_pin.value() == 0:
                selected_answer = "D"
                print("Option D selected")
                time.sleep(0.2)

        save_answer_to_sdcard(question_num, selected_answer)
        led2_pin.value(0)
        led1_pin.value(1)
        time.sleep(1)
        led1_pin.value(0)
    else:
        print("Question already answered or Timer not running")

def main():
    """Main program loop."""
    create_empty_answers_file() # Create answers.txt at startup if it doesn't exist
    print("Client Started. Waiting for RFID cards...")

    while True:
        reader.init()
        (stat, tag_type) = reader.request(reader.REQIDL)
        if stat == reader.OK:
            (stat, raw_uid) = reader.anticoll(reader.PICC_ANTICOLL1)
            if stat == reader.OK:
                uid = list(raw_uid)
                uid_str = byte_array_to_str(uid)
                print(f"Card Detected: UID = {uid_str}")

                if uid == START_UID:
                    handle_start_card(uid_str)
                elif uid == STOP_TIMER_UID:
                    handle_stop_card(uid_str, uid) # Pass uid bytes
                elif uid == WIFI_SEND_DATA_UID:
                    handle_wifi_send_card(uid_str, uid) # Pass uid bytes
                else:
                    question_num = QUESTIONS.get(uid_str)
                    if question_num:
                        handle_question_card(uid_str, question_num)
                    else:
                        print("Unauthorized Access (Unknown UID)")

                if reader.PcdSelect(raw_uid, reader.PICC_ANTICOLL1) == 0: # Changed to check for success (0)
                    print("Card selected")
                # removed else branch to avoid "Card selection failed" message

                reader.stop_crypto1()

        if timer_running:
            current_time = time.ticks_ms()
            elapsed_time = (current_time - timer_start_time) // 1000
            print("Time:", elapsed_time)
            time.sleep(1)

        time.sleep(0.1)

if __name__ == "__main__":
    main()

