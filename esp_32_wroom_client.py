# client.py
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
# ... (rest of SPI and Pin configurations as before)
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
rst_rfid = 22

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
#----- Device Instantiation ----- # Commented out as instantiation happens later where needed
#SD Card # Instantiation moved to main to handle potential SD card issues later
#sd = sdcard.SDCard(spi_sd, Pin(cs_sd))

#Mount filesystem # Mounted inside main function
#vfs = os.VfsFat(sd) # Instantiation moved to main
#os.mount(vfs, "/sd")

# RFID Reader
reader = mfrc522.MFRC522(sck=sck_rfid, mosi=mosi_rfid, miso=miso_rfid, rst=rst_rfid, cs=cs_rfid)

# ----- Target RFID UIDs -----
# START_UID = [0xF3, 0xC7, 0x1A, 0x13, 0x3D]  # Start tag UID - REMOVED
STOP_TIMER_UID = [0x00, 0x64, 0x56, 0xD3, 0xE1]  # Stop Timer tag UID
WIFI_SEND_DATA_UID = [0xD3, 0x34, 0xE7, 0x11, 0x11] # UID to trigger Wi-Fi connection and data send
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

# --- Category UIDs (now also act as start UIDs) ---
CATEGORY1_UID = [0xF3, 0xC7, 0x1A, 0x13, 0x3D]  # Category 1 UID (and Start for Category 1)
CATEGORY2_UID = [0x8A, 0x8D, 0x57, 0x54, 0x04]  # Category 2 UID (and Start for Category 2)
CATEGORY3_UID = [0x12, 0x9C, 0x19, 0xFA, 0x6D]  # Category 3 UID (and Start for Category 3)

#----- State Variables -----
current_question = 0
selected_answer = None
timer_running = False
timer_start_time = 0
elapsed_time = 0
timer_stopped = False
answers = {}  # Dictionary to store selected answers: {question_num: answer}
last_category_uid = None # Variable to store the last scanned category UID

#----- Helper Functions -----
def byte_array_to_str(byte_arr):
    """Converts a byte array to a byte array to a hex string (e.g., [0x12, 0xAB] -> "0x120xAB")."""
    return "".join(["0x{:02X}".format(x) for x in byte_arr])

def save_time_to_sdcard(elapsed_time):
    """Saves the elapsed time to the timer_log.txt file on the SD card."""
    try:
        with open("/sd/timer_log.txt", "w") as f:
            f.write("Time: {} seconds\n".format(elapsed_time)) # use .format instead of f-string
        print("Time saved to SD card")
    except Exception as e:
        print("Error saving to SD card: {}".format(e)) # use .format instead of f-string

def read_time_from_sdcard():
    """Reads the elapsed time from the timer_log.txt file on the SD card."""
    try:
        with open("/sd/timer_log.txt", "r") as f:
            time_str = f.readline().split(":")[1].strip().split(" ")[0]  # Extract time value
        return float(time_str)
    except Exception as e:
        print("Error reading time from SD card: {}".format(e)) # use .format instead of f-string
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
        print("Error reading answers from SD card: {}".format(e)) # use .format instead of f-string
    return answers

def save_answer_to_sdcard(question_num, answer):
    """Saves the selected answer for a question to the answers.txt file."""
    global answers
    try:
        answers[question_num] = answer
        with open("/sd/answers.txt", "a") as f:
            f.write("{}: {}\n".format(question_num, answer)) # use .format instead of f-string
        print("Question {} - Answer saved to SD card".format(question_num)) # use .format instead of f-string
    except Exception as e:
        print("Error saving to SD card: {}".format(e)) # use .format instead of f-string

def create_empty_answers_file():
    """Creates an empty answers.txt file on the SD card."""
    try:
        with open("/sd/answers.txt", "w") as f:
            print("Empty answers file created on the SD card")
    except Exception as e:
        print("Error creating answers file on SD card: {}".format(e)) # use .format instead of f-string

def delete_answer_time_files():
    """Deletes answers.txt and timer_log.txt files from the SD card."""
    files_to_delete = ["/sd/answers.txt", "/sd/timer_log.txt"]
    for file_path in files_to_delete:
        try:
            os.remove(file_path)
            print("Deleted file: {}".format(file_path)) # use .format instead of f-string
        except OSError as e:
            if e.args[0] == 2:  # FileNotFoundError
                print("File not found, skipping deletion: {}".format(file_path)) # use .format instead of f-string
            else:
                print("Error deleting file {}: {}".format(file_path, e)) # use .format instead of f-string

#--- Function to Send Data to Server ---
def send_data(name, sta, category_uid_str): # Added category_uid_str parameter
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
        "answers": answers_from_sd, # Include answers in payload
        "category_uid": category_uid_str # Include category UID string
    }
    json_data = json.dumps(data_payload) # Convert to JSON string
    print("JSON Payload to send:", json_data) # Debug print JSON data

    for attempt in range(retries):
        try:
            print("Attempting to connect to server: {}:{} (Attempt {}/{})".format(server_ip, server_port, attempt+1, retries)) # use .format instead of f-string
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5) # Set timeout for connection and receiving
            s.connect((server_ip, server_port))
            print("Connected to server.") # Debug connection success

            request = "POST /add HTTP/1.1\r\nHost: {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{}".format(server_ip, len(json_data), json_data) # use .format instead of f-string, Content-Type: application/json
            print("Sending HTTP Request:\n", request) # Debug print HTTP request

            s.sendall(request.encode())
            print("Request sent.") # Debug request send

            response = s.recv(1024)
            print("Server Response:", response.decode()) # Debug server response

            s.close()
            print("Socket closed.") # Debug socket close
            return True

        except Exception as e:
            print("Error sending data (attempt {}/{}): {}".format(attempt+1, retries, e)) # use .format instead of f-string, Keep original error print
            if attempt < retries - 1:
                print("Retrying in {} seconds...".format(retry_delay)) # use .format instead of f-string
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

#--- Modified handle_start_card function (renamed to handle_category_card) ---
def handle_category_card(uid_str, uid_bytes): # Pass uid_bytes
    """Handles the Category card logic (now also starts timer)."""
    global timer_running, timer_stopped, timer_start_time, current_question, answers, last_category_uid

    if timer_running:
        timer_running = False
        timer_stopped = True
    print("Category Card Scanned: UID = {}".format(uid_str)) # use .format instead of f-string, Indicate category card is scanned
    timer_start_time = time.ticks_ms()
    timer_running = True
    timer_stopped = False
    current_question = 0
    answers = {}
    last_category_uid = uid_bytes # Store the category UID bytes
    print("Project Reset - Timer Started for Category: {}".format(uid_str)) # use .format instead of f-string, Indicate category start
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
    global timer_stopped, last_category_uid

    if timer_stopped: # Only connect if timer is stopped
        if last_category_uid is None:
            print("Please scan a category card before sending data.")
            led2_pin.value(1)
            time.sleep(2)
            led2_pin.value(0)
            return

        print("Connecting to Wi-Fi and Sending Data...")
        time.sleep(1) # Keep a small delay before Wi-Fi connection

        # --- Connect to Wi-Fi (Only when WIFI_SEND_DATA_UID card is scanned) ---
        sta = network.WLAN(network.STA_IF) # Create sta object here
        sta.active(True)
        print("Attempting to connect to Wi-Fi SSID: '{}'".format(ssid)) # use .format instead of f-string, Debug SSID
        sta.connect(ssid, password)

        wifi_connect_timeout = time.time() + 10 # 10 seconds timeout for Wi-Fi connection
        while not sta.isconnected() and time.time() < wifi_connect_timeout:
            print("Connecting to Wi-Fi...")
            time.sleep(1)

        if sta.isconnected():
            print("Connected to Wi-Fi. IP:", sta.ifconfig()[0])
            rssi = sta.status('rssi') # Get RSSI
            print("Wi-Fi RSSI: {} dBm".format(rssi)) # use .format instead of f-string, Print RSSI

            category_uid_str = byte_array_to_str(last_category_uid) # Convert category UID to string for sending
            # --- Send Data to Server ---
            if send_data("Client1", sta, category_uid_str): # Call send_data, no time argument needed, pass category UID string
                print("Data sent to server successfully.")
                led1_pin.value(1) # Indicate success with LED
                time.sleep(2)
                led1_pin.value(0)
                last_category_uid = None # Reset category after successful send
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
        print("Question {} active".format(question_num)) # use .format instead of f-string
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
    global last_category_uid, sd, vfs # Declare sd and vfs as global
    sd = sdcard.SDCard(spi_sd, Pin(cs_sd)) # Instantiate SD card here - try moving this inside the try block if still failing
    vfs = os.VfsFat(sd) # Instantiate VFS here - try moving this inside the try block if still failing
    try: # Added try-except block around SD card mounting
        os.mount(vfs, "/sd") # Mount SD card filesystem
        print("SD card mounted successfully!") # Add print to confirm mount
    except OSError as e:
        print("SD Card Mount Error: {}".format(e)) # Print specific SD card mount error
        print("Please check:")
        print("- SD card is properly inserted.")
        print("- Wiring to SD card module (SPI pins and CS).")
        print("- SD card is formatted as FAT32 or FAT16.")
        print("Halting program.")
        return # Stop execution if SD card mount fails - important!

    create_empty_answers_file() # Create answers.txt at startup if it doesn't exist
    print("Client Started. Waiting for RFID cards...")

    sta = network.WLAN(network.STA_IF) # define sta here to use in finally block
    sta.active(True)

    try:
        while True:
            reader.init()
            (stat, tag_type) = reader.request(reader.REQIDL)
            if stat == reader.OK:
                (stat, raw_uid) = reader.anticoll(reader.PICC_ANTICOLL1)
                if stat == reader.OK:
                    uid = list(raw_uid)
                    uid_str = byte_array_to_str(uid)
                    print("Card Detected: UID = {}".format(uid_str)) # use .format instead of f-string

                    # --- Category UIDs now also start the timer ---
                    if uid == CATEGORY1_UID:
                        handle_category_card(uid_str, uid) # Call handle_category_card for Category 1
                    elif uid == CATEGORY2_UID:
                        handle_category_card(uid_str, uid) # Call handle_category_card for Category 2
                    elif uid == CATEGORY3_UID:
                        handle_category_card(uid_str, uid) # Call handle_category_card for Category 3
                    elif uid == STOP_TIMER_UID:
                        handle_stop_card(uid_str, uid)
                    elif uid == WIFI_SEND_DATA_UID:
                        handle_wifi_send_card(uid_str, uid)
                    else: # Question cards and unauthorized access remain the same
                        question_num = QUESTIONS.get(uid_str)
                        if question_num:
                            handle_question_card(uid_str, question_num)
                        else:
                            print("Unauthorized Access (Unknown UID)")

                    if reader.PcdSelect(raw_uid, reader.PICC_ANTICOLL1) == 0:
                        print("Card selected")

                    reader.stop_crypto1()

            if timer_running:
                current_time = time.ticks_ms()
                elapsed_time = (current_time - timer_start_time) // 1000
                print("Time:", elapsed_time)
                time.sleep(1)

            time.sleep(0.1)
    finally:
        sta.active(False) # turn off wifi in case of errors or program exit

if __name__ == "__main__":
    main()
