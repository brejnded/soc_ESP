import network
import usocket as socket
import time
import machine
from machine import Pin, SPI
import os
import mfrc522
import sdcard
import json
import sys

# Wi-Fi
ssid = "ESP32"
password = "SPSIT123"
server_ip = "192.168.4.1"
server_port = 80
# SD karta SPI 1 (HSPI)
sck_sd = 14
mosi_sd = 13
miso_sd = 12
cs_sd = 2
# RFID SPI 0 (VSPI)
sck_rfid = 18
mosi_rfid = 23
miso_rfid = 19
rst_rfid = 22
cs_rfid = 5
# Piny LED diód
led1_pin_num = 33
led2_pin_num = 32

button_a_pin_num = 16
button_b_pin_num = 21
button_c_pin_num = 26
button_d_pin_num = 27
button_confirm_pin_num = 15

# --- Inicializácia hardvéru ---
# LED diódy
led1_pin = Pin(led1_pin_num, Pin.OUT)
led2_pin = Pin(led2_pin_num, Pin.OUT)
led1_pin.value(0)
led2_pin.value(0)
# Tlačidlá
button_a_pin = Pin(button_a_pin_num, Pin.IN, Pin.PULL_UP)
button_b_pin = Pin(button_b_pin_num, Pin.IN, Pin.PULL_UP)
button_c_pin = Pin(button_c_pin_num, Pin.IN, Pin.PULL_UP)
button_d_pin = Pin(button_d_pin_num, Pin.IN, Pin.PULL_UP)
button_confirm_pin = Pin(button_confirm_pin_num, Pin.IN, Pin.PULL_UP)

# SD karta SPI
spi_sd = SPI(1, baudrate=1000000, polarity=0, phase=0, sck=Pin(sck_sd), mosi=Pin(mosi_sd), miso=Pin(miso_sd))
sd = None
vfs = None

# Čítačka RFID
reader = mfrc522.MFRC522(sck=sck_rfid, mosi=mosi_rfid, miso=miso_rfid, rst=rst_rfid, cs=cs_rfid)

# RFID UID
START_TIMER_UID = [0x88, 0x04, 0x81, 0xB5, 0xB8] # <<<< NEW START UID
STOP_TIMER_UID = [0x00, 0x64, 0x56, 0xD3, 0xE1]
WIFI_SEND_DATA_UID = [0xD3, 0x34, 0xE7, 0x11, 0x11]
ADD_1_MINUTE_UID = [0x88, 0x04, 0x6C, 0xD5, 0x35]
ADD_2_MINUTE_UID = [0x11, 0x22, 0x33, 0x44, 0x52]
ADD_3_MINUTE_UID = [0x11, 0x22, 0x33, 0x44, 0x53]
CATEGORY1_UID = [0xF3, 0xC7, 0x1A, 0x13, 0x3D]
CATEGORY2_UID = [0x8A, 0x8D, 0x57, 0x54, 0x04]
CATEGORY3_UID = [0x12, 0x9C, 0x19, 0xFA, 0x6D]

QUESTIONS = {
    "0x730xED0xBF0x2C0x0D": 1, "0x230xBA0xCB0x2C0x7E": 2, "0x230xB80x9F0x2C0x28": 3,
    "0xD30x910xBF0x2C0xD1": 4, "0x730x2A0xD00x2C0xA5": 5, "0x830xED0xCF0x2C0x8D": 6,
    "0xB30x970xB40x2C0xBC": 7, "0xE30x110xBF0x2C0x61": 8, "0xD30x6E0xCE0x2C0x5F": 9,
    "0xB30xAA0xCD0x2C0xF8": 10,"0xC30xE40xB90x2C0xB2": 11,"0x530xB30xCD0x2C0x01": 12,
    "0x830x740xF80x2C0x23": 13,"0xE30xD40xCB0x2C0xD0": 14,"0x130xE90xA00x2C0x76": 15
}

current_question = 0
timer_running = False
timer_start_time = 0
elapsed_time = 0
timer_stopped = False # Indicates if timer has been explicitly stopped by STOP card
answers = {}
last_category_uid = None # Stores the UID of the last scanned category card

# Stav pre blikanie počas odosielania
sending_in_progress = False
last_sending_blink_time = 0
SENDING_BLINK_INTERVAL_MS = 100   # Interval blikania (ms) pre LED1 počas odosielania

SD_MOUNT_POINT = "/sd"
ANSWERS_FILE_PATH = SD_MOUNT_POINT + "/answers.txt"
TIMER_FILE_PATH = SD_MOUNT_POINT + "/timer_log.txt"

#----- Pomocné funkcie -----
def byte_array_to_str(byte_arr):
    """Prevedie bajtové pole na hexadecimálny formát."""
    if byte_arr is None: return ""
    return "".join(["0x{:02X}".format(x) for x in byte_arr])

def blink_led(pin, num_blinks, on_duration_seconds, off_duration_seconds):
    """Blikne  zadaný počet krát, s ohľadom na sending_in_progress."""
    global sending_in_progress

    was_sending = (pin == led1_pin and sending_in_progress)

    try:
        if was_sending:
            sending_in_progress = False
            pin.value(0)
            time.sleep_ms(10)

        for i in range(num_blinks):
            pin.value(1)
            time.sleep(on_duration_seconds)
            if not (pin == led1_pin and sending_in_progress):
                 pin.value(0)

            if i < num_blinks - 1 or off_duration_seconds > 0.01:
                 if not (pin == led1_pin and sending_in_progress):
                     time.sleep(off_duration_seconds)
    finally:
        if was_sending:
            sending_in_progress = True

# Funkcie SD karty
def save_time_to_sdcard(time_seconds):
    """Uloží konečný uplynulý čas do súboru denníka časovača."""
    if vfs is None:
        print("SD karta nie je pripojená. Nie je možné uložiť čas.")
        blink_led(led2_pin, 4, 0.1, 0.1)
        return False
    try:
        with open(TIMER_FILE_PATH, "w") as f: # Prepíše existujúci súbor
            f.write(f"Time: {time_seconds} seconds\n")
        print(f"Čas ({time_seconds}s) uložený do {TIMER_FILE_PATH}")
        return True
    except Exception as e:
        print(f"Chyba pri ukladaní času na SD kartu: {e}")
        blink_led(led2_pin, 3, 0.1, 0.1)
        return False

def read_time_from_sdcard():
    """Prečíta uplynulý čas z SD karty"""
    if vfs is None:
        print("SD karta nie je pripojená. Nie je možné prečítať čas.")
        return None
    try:
        with open(TIMER_FILE_PATH, "r") as f:
            line = f.readline()
            if line and "Time:" in line:
                parts = line.split(":")
                if len(parts) > 1:
                     time_str = parts[1].strip().split(" ")[0]
                     return float(time_str)
                else:
                     print(f"Chyba: Neplatný formát v {TIMER_FILE_PATH}")
                     return None
            else:
                print(f"Chyba: Neplatný formát alebo prázdny súbor: {TIMER_FILE_PATH}")
                return None
    except OSError:
        print(f"Info: Súbor časovača nebol nájdený: {TIMER_FILE_PATH}")
        return None
    except Exception as e:
        print(f"Chyba pri čítaní času z SD karty: {e}")
        return None

def read_answers_from_sdcard():
    """Prečíta odpovede zo súboru answers.txt (formát riadku: O#: O). Vráti slovník."""
    if vfs is None:
        print("SD karta nie je pripojená. Nie je možné prečítať odpovede.")
        return {}
    answers_local = {}
    try:
        with open(ANSWERS_FILE_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                parts = line.split(":")
                if len(parts) == 2:
                    try:
                        q_num = int(parts[0].strip())
                        ans = parts[1].strip()
                        answers_local[q_num] = ans
                    except ValueError:
                        print(f"Preskakuje sa neplatný riadok (neceločíselné O#) v {ANSWERS_FILE_PATH}: {line}")
                else:
                     print(f"Preskakuje sa nesprávne formátovaný riadok v {ANSWERS_FILE_PATH}: {line}")
    except OSError:
        print(f"Info: Súbor s odpoveďami nebol nájdený ({ANSWERS_FILE_PATH}). Začína sa nanovo.")
    except Exception as e:
        print(f"Chyba pri čítaní odpovedí z SD karty: {e}")
        blink_led(led2_pin, 3, 0.1, 0.1)
    return answers_local

def save_answer_to_sdcard(question_num, answer):
    """Zapíše zvolenú odpoveď na otázku do súboru answers.txt."""
    global answers
    if vfs is None:
        print("SD karta nie je pripojená. Nie je možné uložiť odpoveď.")
        blink_led(led2_pin, 4, 0.1, 0.1)
        return False
    try:
        answers[question_num] = answer # Update in-memory dictionary
        # We will write all answers at once if needed, or line by line
        # For robustness, appending is better if power loss is a concern
        with open(ANSWERS_FILE_PATH, "a") as f:
            f.write(f"{question_num}: {answer}\n")
        print(f"Otázka {question_num} - Odpoveď '{answer}' pripojená do {ANSWERS_FILE_PATH}")
        return True
    except Exception as e:
        print(f"Chyba pri ukladaní odpovede na SD kartu: {e}")
        blink_led(led2_pin, 3, 0.1, 0.1)
        return False

def create_empty_answers_file():
    """Vytvorí prázdny súbor answers.txt na SD karte, prepíše ho, ak existuje."""
    if vfs is None:
        print("SD karta nie je pripojená. Nie je možné vytvoriť/vymazať súbor s odpoveďami.")
        return
    try:
        with open(ANSWERS_FILE_PATH, "w") as f:
            pass # Just create/truncate the file
        print(f"Vytvorený/Vymazaný prázdny súbor s odpoveďami: {ANSWERS_FILE_PATH}")
    except Exception as e:
        print(f"Chyba pri vytváraní/mazaní súboru s odpoveďami: {e}")
        blink_led(led2_pin, 3, 0.1, 0.1)

def delete_answer_time_files():
    """Odstráni súbory answers.txt a timer_log.txt z SD karty."""
    if vfs is None:
        print("SD karta nie je pripojená. Nie je možné odstrániť súbory.")
        return
    files_to_delete = [ANSWERS_FILE_PATH, TIMER_FILE_PATH]
    print("Odstraňujú sa súbory predchádzajúceho behu...")
    for file_path in files_to_delete:
        try:
            os.remove(file_path)
            print(f"Odstránené: {file_path}")
        except OSError as e:
            if e.args[0] == 2: # Súbor Nenájdený (errno 2 is ENOENT)
                print(f"Info: Súbor nebol nájdený, preskakuje sa odstránenie: {file_path}")
            else:
                print(f"Chyba pri odstraňovaní súboru {file_path}: {e}")
                blink_led(led2_pin, 2, 0.1, 0.1)

# odoslanie dát na server
def send_data(name, sta_interface, category_uid_str):
    """Pripojí sa k serveru, odošle dátový payload, spracuje opätovné pokusy a signalizuje stav."""
    global sending_in_progress, last_sending_blink_time, last_category_uid

    retries = 3
    retry_delay = 1
    success = False

    elapsed_time_from_sd = read_time_from_sdcard()
    answers_from_sd = read_answers_from_sdcard()

    if elapsed_time_from_sd is None:
        print("Nepodarilo sa prečítať čas z SD karty. Odosielanie sa prerušuje.")
        blink_led(led2_pin, 4, 0.1, 0.1)
        return False
    if not isinstance(answers_from_sd, dict): # Should be a dictionary
        print(f"Chyba: Odpovede prečítané z SD nie sú slovník: {answers_from_sd}")
        blink_led(led2_pin, 4, 0.1, 0.1)
        return False

    data_payload = {
        "name": name,
        "time": elapsed_time_from_sd,
        "answers": answers_from_sd, # Send the dictionary directly
        "category_uid": category_uid_str
    }
    try:
        json_data = json.dumps(data_payload)
    except Exception as e:
        print(f"Chyba pri konverzii dát na JSON: {e}")
        blink_led(led2_pin, 3, 0.1, 0.1)
        return False

    print("JSON Payload na odoslanie:", json_data)

    print("Spúšťa sa pokus o prenos dát...")
    sending_in_progress = True
    last_sending_blink_time = time.ticks_ms()
    led1_pin.value(1) # Solid ON during connection attempts

    try:
        for attempt in range(retries):
            s = None
            try:
                print(f"Pripája sa k serveru: {server_ip}:{server_port} (Pokus {attempt+1}/{retries})")
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(10) # Socket timeout for connect and recv
                s.connect(socket.getaddrinfo(server_ip, server_port)[0][-1])
                print("Pripojené k serveru.")

                request = f"POST /add HTTP/1.1\r\nHost: {server_ip}\r\nContent-Type: application/json\r\nContent-Length: {len(json_data)}\r\nConnection: close\r\n\r\n{json_data}"
                print("Odosiela sa HTTP požiadavka...")
                s.sendall(request.encode('utf-8'))
                print("Požiadavka odoslaná.")

                print("Čaká sa na odpoveď servera...")
                response_bytes = b""
                try:
                     while True: # Read response in chunks
                          chunk = s.recv(512)
                          if not chunk: break # Connection closed by server
                          response_bytes += chunk
                except socket.timeout:
                     print("Počas prijímania odpovede došlo k vypršaniu časového limitu.")
                # except OSError as e:
                #     if e.args[0] == 11: # EAGAIN, non-blocking socket would return this
                #         pass # For non-blocking, just try again
                #     else:
                #         raise e


                response_str = response_bytes.decode('utf-8')
                print(f"Odpoveď servera prijatá (prvých 200 znakov): {response_str[:200]}")

                # Check for HTTP 200 OK
                if response_str.startswith("HTTP/1.1 200 OK"):
                    print(">>> Dáta úspešne odoslané a potvrdené serverom (200 OK).")
                    success = True
                    break # Exit retry loop on success
                else:
                    print(f"Server vrátil iný stav ako 200 pri pokuse {attempt+1}. Odpoveď: {response_str[:200]}")

            except OSError as e: # Catch network/socket errors
                 print(f"Chyba siete/soketu (Pokus {attempt+1}): {e}")
            except Exception as e:
                print(f"Neočakávaná chyba pri odosielaní dát (Pokus {attempt+1}): {e}")
            finally:
                if s:
                    s.close()
                    print("Soket zatvorený.")

            if not success and attempt < retries - 1:
                print(f"Opakovaný pokus za {retry_delay} sekúnd...")
                time.sleep(retry_delay)
                retry_delay *= 2 # Exponential backoff
            elif not success:
                 print("Maximálny počet pokusov dosiahnutý. Prenos dát zlyhal.")

    finally:
        sending_in_progress = False # Stop blinking/solid LED
        led1_pin.value(0) # Ensure LED1 is off after send attempt
        print("Proces prenosu dát ukončený.")

        if success:
            print("Vykonáva sa signalizačné blikanie ÚSPECHU (LED1)...")
            blink_led(led1_pin, 3, 1, 0.5) # Long blinks for success
            last_category_uid = None # Reset category after successful send
                                    # to force new category selection for next run
        else:
            print("Vykonáva sa signalizačné blikanie ZLYHANIA (LED2)...")
            blink_led(led2_pin, 5, 0.2, 0.2) # Fast blinks for failure

    # Disconnect Wi-Fi after sending attempt (regardless of success)
    if sta_interface and sta_interface.isconnected():
        print("Odpája sa od Wi-Fi...")
        sta_interface.disconnect()
        disconnect_start = time.ticks_ms()
        while sta_interface.isconnected() and time.ticks_diff(time.ticks_ms(), disconnect_start) < 5000: # 5s timeout
            print(".")
            time.sleep(0.5)
        if sta_interface.isconnected(): print("Varovanie: Nepodarilo sa korektne odpojiť.")
        else: print("Odpojené od Wi-Fi.")
    # No need to sta_interface.active(False) here, do it in main cleanup if needed

    return success

# Funkcie pre spracovanie kariet

def handle_category_card(uid_str, uid_bytes):
    """Spracuje kartu Kategórie: Resetuje stav, súbory, pripraví pre spustenie časovača."""
    global timer_running, timer_stopped, current_question, answers, last_category_uid, sending_in_progress

    if timer_running and not timer_stopped: # If timer is active from a previous start
        print("Varovanie: Nová karta kategórie naskenovaná počas behu časovača. Resetuje sa relácia.")
        timer_running = False
        timer_stopped = True # Treat as if it was stopped to allow clean restart logic below
        # No need to save partial time, as a new category implies a full reset

    print(f"Karta Kategórie naskenovaná: {uid_str}. Toto bude aktívna kategória.")
    last_category_uid = uid_bytes # Store the UID of this category card
    current_question = 0
    answers = {} # Reset in-memory answers

    # Reset state for a new run with this category
    print("--- Resetuje sa priebeh projektu pre výber novej kategórie ---")
    delete_answer_time_files() # Delete old answers.txt and timer_log.txt
    create_empty_answers_file() # Create a fresh, empty answers.txt

    timer_running = False # Ensure timer is marked as not running yet
    timer_stopped = False # Reset stopped state as well
    # elapsed_time and timer_start_time will be set by the START_TIMER_UID card

    print(f"Kategória {byte_array_to_str(last_category_uid)} zvolená. Naskenujte ŠTART kartu pre začatie časovača.")
    led2_pin.value(0) # Ensure error LED is off
    blink_led(led1_pin, 2, 0.3, 0.3) # Signal category selection (e.g., 2 short blinks on LED1)
    # ČASOVAČ SA TU NEŠTARTUJE

def handle_start_timer_card(uid_str, uid_bytes):
    """Spracuje kartu ŠTART ČASOVAČA: Spustí časovač, ak bola predtým zvolená kategória."""
    global timer_running, timer_stopped, timer_start_time, elapsed_time, last_category_uid, sending_in_progress

    if last_category_uid is None:
        print("Chyba: ŠTART karta naskenovaná, ale žiadna kategória nebola ešte zvolená.")
        print("Prosím, najprv naskenujte kartu KATEGÓRIE.")
        blink_led(led2_pin, 3, 0.2, 0.2) # Error signal
        return

    if timer_running:
        print("Varovanie: ŠTART karta naskenovaná, ale časovač už beží. Ignoruje sa.")
        blink_led(led2_pin, 1, 0.2, 0.0) # Short warning
        return

    # If a previous run was stopped (timer_stopped is True), or this is a fresh start
    print(f"ŠTART ČASOVAČA karta naskenovaná: {uid_str} pre kategóriu {byte_array_to_str(last_category_uid)}")

    timer_start_time = time.ticks_ms()
    elapsed_time = 0 # Reset elapsed time for this run
    timer_running = True
    timer_stopped = False # Explicitly set to False

    print("--> Časovač spustený! <---")
    led2_pin.value(0) # Ensure error LED is off

    # 10-sekundové blikanie na LED1
    blink_duration_ms = 10000
    blink_on_ms = 100
    blink_off_ms = 100

    original_sending_state = sending_in_progress # Preserve state if send was interrupted
    try:
        if original_sending_state: # Temporarily stop send-blinking if it was active
            sending_in_progress = False
            led1_pin.value(0)
            time.sleep_ms(10) # Small delay

        blink_count = blink_duration_ms // (blink_on_ms + blink_off_ms)
        # Use the main blink_led function which handles sending_in_progress
        blink_led(led1_pin, blink_count, blink_on_ms / 1000.0, blink_off_ms / 1000.0)

    finally:
        if original_sending_state: # Restore sending_in_progress if it was true
             sending_in_progress = True
        if not sending_in_progress: # Ensure LED1 is off if not sending
            led1_pin.value(0)


def handle_stop_card(uid_str, uid_bytes):
    """Spracuje kartu STOP: Zastaví časovač, vypočíta konečný čas, uloží ho na SD."""
    global timer_running, timer_stopped, elapsed_time, timer_start_time

    print(f"STOP karta naskenovaná: {uid_str}")
    if timer_running and not timer_stopped: # Timer is active and not already stopped
        current_ticks = time.ticks_ms()
        elapsed_ms = time.ticks_diff(current_ticks, timer_start_time)
        elapsed_time = elapsed_ms // 1000 # Final elapsed time in seconds

        timer_running = False # Stop the timer logic
        timer_stopped = True  # Mark that the timer has been explicitly stopped
        print(f"--> Časovač zastavený! Konečný uplynulý čas: {elapsed_time} sekúnd <---")
        led1_pin.value(0) # Turn off LED1 (if it was blinking for timer start)
        led2_pin.value(0) # Ensure error LED is off

        if save_time_to_sdcard(elapsed_time):
            print("Čas úspešne uložený na SD kartu.")
            blink_led(led1_pin, 2, 0.5, 0.5) # Signal success
            print("Pripravené na odoslanie dát (naskenujte kartu WIFI SEND).")
        else:
            print("Nepodarilo sa uložiť čas na SD kartu!")
            # Error already blinked by save_time_to_sdcard

        # Log final answers for verification if needed
        final_answers_on_sd = read_answers_from_sdcard()
        print(f"Konečné odpovede zaznamenané na SD: {final_answers_on_sd}")

    elif timer_stopped:
        print("Časovač je už zastavený.")
        blink_led(led2_pin, 1, 0.1, 0) # Short blink, e.g. on LED2
    else: # Timer was not running when STOP card scanned
        print("Časovač nebežal, keď bola naskenovaná karta STOP.")
        blink_led(led2_pin, 2, 0.1, 0.1)


def handle_wifi_send_card(uid_str, uid_bytes):
    """Spracuje kartu WIFI SEND: Skontroluje stav, pripojí Wi-Fi, zavolá send_data."""
    global timer_stopped, last_category_uid # timer_running is not directly needed here

    print(f"WIFI SEND karta naskenovaná: {uid_str}")

    if not timer_stopped: # Timer must be stopped (meaning a run was completed)
        print("Chyba: Časovač musí byť zastavený pred odoslaním dát. Najprv naskenujte kartu STOP.")
        blink_led(led2_pin, 3, 0.1, 0.1)
        return
    if last_category_uid is None: # A category must have been part of this run
        print("Chyba: UID kategórie nie je zaznamenané. Spustite beh najprv s kartou kategórie a štart kartou.")
        blink_led(led2_pin, 4, 0.1, 0.1)
        return

    print("Pokračuje sa pripojením k Wi-Fi a prenosom dát...")

    sta = network.WLAN(network.STA_IF)
    if not sta.active(): sta.active(True)

    if not sta.isconnected():
        print(f"Pokus o pripojenie k Wi-Fi SSID: '{ssid}'...")
        sta.connect(ssid, password)
        connect_start = time.ticks_ms()
        timeout_ms = 15000 # 15 seconds timeout for Wi-Fi connection
        wifi_connect_led_state = 0
        while not sta.isconnected() and time.ticks_diff(time.ticks_ms(), connect_start) < timeout_ms:
            print("Pripája sa...")
            wifi_connect_led_state = 1 - wifi_connect_led_state # Toggle
            led2_pin.value(wifi_connect_led_state) # Blink LED2 during connection attempt
            time.sleep(0.5)
        led2_pin.value(0) # Turn off LED2 after attempt

    if sta.isconnected():
        print("Wi-Fi úspešne pripojené.")
        print("IP Adresa:", sta.ifconfig()[0])
        try:
            rssi = sta.status('rssi') # Get Wi-Fi signal strength
            print(f"Sila signálu Wi-Fi (RSSI): {rssi} dBm")
        except: pass # Ignore if RSSI is not available

        category_uid_str = byte_array_to_str(last_category_uid)
        send_success = send_data("Zariadenie", sta, category_uid_str) # Pass sta_interface

        if send_success:
            print("Proces prenosu dát úspešne dokončený.")
            # last_category_uid is reset inside send_data on success
        else:
            print("Proces prenosu dát zlyhal po opätovných pokusoch.")
        # Wi-Fi will be disconnected inside send_data
    else:
        print("Pripojenie k Wi-Fi zlyhalo (Vypršanie časového limitu alebo chyba prihlasovacích údajov).")
        blink_led(led2_pin, 3, 0.3, 0.3)
        # Don't deactivate Wi-Fi here, let main loop's finally handle it
        # if sta.active(): sta.active(False) # Could be done, but risky if other parts expect it active


def handle_question_card(uid_str, question_num):
    global answers, timer_running, sending_in_progress # Added timer_running and sending_in_progress
    print(f"OTÁZKA karta naskenovaná: O{question_num} ({uid_str})")

    if not timer_running:
        print("Časovač nebeží. Teraz nie je možné odpovedať na otázky.")
        blink_led(led2_pin, 2, 0.1, 0.1)
        return
    if question_num in answers:
        print(f"Na otázku {question_num} už bolo odpovedané ('{answers[question_num]}'). Karta sa ignoruje.")
        blink_led(led2_pin, 2, 0.05, 0.05) # Quick double blink on LED2
        return

    print(f"Otázka {question_num} aktívna. Vyberte odpoveď (A/B/C/D) a stlačte POTVRDIŤ.")
    local_selected_answer = None
    if not sending_in_progress: led1_pin.value(0) # Ensure LED1 is off unless sending

    # Blinking LED2 to indicate waiting for answer input
    last_answer_blink_time = time.ticks_ms()
    led2_state = 1
    led2_pin.value(led2_state)
    ANSWER_BLINK_INTERVAL_MS = 250 # Slower blink for answer mode

    confirm_pressed_time = -1
    button_debounce_delay_ms = 50 # ms to wait after first press detection
    input_active = True

    while input_active:
        current_time_ms = time.ticks_ms()

        # Blink LED2 while waiting for input
        if time.ticks_diff(current_time_ms, last_answer_blink_time) >= ANSWER_BLINK_INTERVAL_MS:
            led2_state = 1 - led2_state
            led2_pin.value(led2_state)
            last_answer_blink_time = current_time_ms

        # Check confirm button
        if button_confirm_pin.value() == 0: # Pressed (active low)
             if confirm_pressed_time < 0: # First detection
                 confirm_pressed_time = current_time_ms
             # Wait for debounce period
             elif time.ticks_diff(current_time_ms, confirm_pressed_time) > button_debounce_delay_ms:
                 print("Tlačidlo Potvrdiť stlačené.")
                 input_active = False # Exit loop after confirm
                 # No need to wait for release for confirm, action on press
        else: # Button not pressed or released
            confirm_pressed_time = -1 # Reset pressed time

        # Check answer buttons (A, B, C, D) - simple check, no complex debounce for selection
        # More robust would be to detect press, then wait for release or timeout
        new_selection = None
        if button_a_pin.value() == 0: new_selection = "A"
        elif button_b_pin.value() == 0: new_selection = "B"
        elif button_c_pin.value() == 0: new_selection = "C"
        elif button_d_pin.value() == 0: new_selection = "D"

        if new_selection is not None and new_selection != local_selected_answer:
            local_selected_answer = new_selection
            print(f"Vybraná odpoveď: {local_selected_answer}")
            # Signal selection change with a quick blink on LED1
            if not sending_in_progress: # Don't interfere with sending blink
                original_led1_val = led1_pin.value()
                led1_pin.value(1)
                time.sleep(0.1) # Short flash
                led1_pin.value(original_led1_val) # Restore previous state or turn off
            time.sleep(0.2) # Debounce/avoid rapid re-selection if button held

        time.sleep(0.02) # Main loop sleep for input handling

    led2_pin.value(0) # Turn off LED2 (answer mode indicator)

    if local_selected_answer is not None:
        print(f"Potvrdzuje sa odpoveď na otázku {question_num}: '{local_selected_answer}'")
        if save_answer_to_sdcard(question_num, local_selected_answer):
             print("Odpoveď uložená.")
             if not sending_in_progress: blink_led(led1_pin, 1, 0.2, 0.1) # Success blink on LED1
        else:
             print("Nepodarilo sa uložiť odpoveď na SD kartu!")
             # Error already blinked by save_answer_to_sdcard
    else:
        print("Potvrdiť stlačené, ale nebola vybraná žiadna odpoveď (A/B/C/D). Otázka zostáva nezodpovedaná.")
        blink_led(led2_pin, 3, 0.1, 0.1) # Error/warning blink

    time.sleep(0.5) # Pause briefly after handling the question


def handle_add_time_card(uid_str, uid_bytes, minutes_to_add):
    """Pridá penalizáciu pomocou prečítania karty"""
    global timer_running, timer_start_time

    print(f"Karta penalizácie naskenovaná: +{minutes_to_add} minúta(y) ({uid_str})")
    if timer_running: # Penalty only if timer is active
        time_to_add_ms = minutes_to_add * 60 * 1000
        timer_start_time -= time_to_add_ms # Effectively adds to elapsed time
        print(f"Penalizácia {minutes_to_add} minút aplikovaná. Čas spustenia časovača upravený.")

        # Display current effective elapsed time
        current_effective_elapsed_ms = time.ticks_diff(time.ticks_ms(), timer_start_time)
        print(f"Aktuálny uplynulý čas (s penalizáciou): {current_effective_elapsed_ms // 1000} sekúnd")

        # Blink LED1 'minutes_to_add' times to confirm
        if not sending_in_progress: blink_led(led1_pin, minutes_to_add, 0.5, 0.5)
    else:
        print("Časovač nebeží. Nie je možné aplikovať penalizáciu.")
        blink_led(led2_pin, 2, 0.1, 0.1)

# --- Hlavná funkcia ---
def main():
    """Vykonanie hlavného programu: Inicializuje hardvér, spracováva skenovanie kariet v slučke."""
    global sd, vfs, answers, sending_in_progress, last_sending_blink_time, timer_running, last_category_uid

    # --- Inicializácia SD karty ---
    try:
        print("Inicializuje sa SD karta...")
        sd = sdcard.SDCard(spi_sd, Pin(cs_sd))
        vfs = os.VfsFat(sd)
        os.mount(vfs, SD_MOUNT_POINT)
        print(f"SD karta úspešne pripojená v {SD_MOUNT_POINT}")
        print("Obsah SD karty:", os.listdir(SD_MOUNT_POINT))
        # answers = read_answers_from_sdcard() # Don't load answers on startup, category selection will clear them
        # print(f"Načítané odpovede z SD: {answers}")
    except OSError as e:
        print(f"Chyba pripojenia SD karty: {e}")
        if e.args[0] == 19: print("Chyba: SD karta nebola detekovaná alebo problém s pripojením (NO_DEVICE).")
        elif e.args[0] == 13: print("Chyba: SD kartu nebolo možné pripojiť (skontrolujte formátovanie - odporúča sa FAT32) (NO_MEM).")
        else: print("Skontrolujte vloženie SD karty, formátovanie a zapojenie (SPI piny, CS pin).")
        print("Program zastavený kvôli chybe SD karty.")
        while True: # Halt with blinking LEDs
            led1_pin.value(not led1_pin.value())
            led2_pin.value(not led1_pin.value()) # Blink both alternately
            time.sleep(0.2)
    except Exception as e:
         print(f"Neočakávaná chyba počas inicializácie SD karty: {e}")
         sys.print_exception(e)
         while True: # Halt with fast blinking
            led1_pin.value(1); led2_pin.value(1); time.sleep(0.1)
            led1_pin.value(0); led2_pin.value(0); time.sleep(0.1)

    print("\nČítačka RFID inicializovaná. Čaká sa na karty...")
    print(f"LED1 (GPIO {led1_pin_num}): Stav/Potvrdenie | LED2 (GPIO {led2_pin_num}): Aktivita/Chyba")
    print("Postup: 1. Karta KATEGÓRIE -> 2. Karta ŠTART ČASOVAČA -> 3. Karty OTÁZOK -> 4. Karta STOP -> 5. Karta WIFI SEND")

    sta = network.WLAN(network.STA_IF) # Get Wi-Fi station interface
    if sta.active(): sta.active(False) # Ensure Wi-Fi is off at start

    last_timer_print_sec = -1

    # Main Loop
    try:
        while True:
            # Handle LED blinking for sending data in progress
            if sending_in_progress:
                current_ticks_ms = time.ticks_ms()
                if time.ticks_diff(current_ticks_ms, last_sending_blink_time) >= SENDING_BLINK_INTERVAL_MS:
                    led1_pin.value(not led1_pin.value()) # Blink LED1
                    last_sending_blink_time = current_ticks_ms
            # If not sending, LED1 is controlled by other functions or off

            # RFID Card Detection
            (stat, tag_type) = reader.request(reader.REQIDL)
            if stat == reader.OK:
                (stat, raw_uid) = reader.anticoll(reader.PICC_ANTICOLL1)
                if stat == reader.OK:
                    uid_bytes = list(raw_uid) # Make it a list for easy comparison
                    uid_str = byte_array_to_str(uid_bytes)
                    print("--------------------")
                    print(f"Karta detekovaná: UID = {uid_str} | Bajty = {uid_bytes}")

                    # --- Card Handling Logic ---
                    if uid_bytes == CATEGORY1_UID or uid_bytes == CATEGORY2_UID or uid_bytes == CATEGORY3_UID:
                        handle_category_card(uid_str, uid_bytes)
                    elif uid_bytes == START_TIMER_UID: # <<<< NEW HANDLER
                        handle_start_timer_card(uid_str, uid_bytes)
                    elif uid_bytes == STOP_TIMER_UID:
                        handle_stop_card(uid_str, uid_bytes)
                    elif uid_bytes == WIFI_SEND_DATA_UID:
                        handle_wifi_send_card(uid_str, uid_bytes)
                    elif uid_bytes == ADD_1_MINUTE_UID:
                        handle_add_time_card(uid_str, uid_bytes, 1)
                    elif uid_bytes == ADD_2_MINUTE_UID:
                        handle_add_time_card(uid_str, uid_bytes, 2)
                    elif uid_bytes == ADD_3_MINUTE_UID:
                        handle_add_time_card(uid_str, uid_bytes, 3)
                    else:
                        question_num = QUESTIONS.get(uid_str)
                        if question_num:
                            handle_question_card(uid_str, question_num)
                        else:
                            print("Detekovaná neoprávnená/neznáma karta.")
                            blink_led(led2_pin, 1, 0.1, 0.05) # Quick blink on LED2

                    reader.stop_crypto1() # Important after successful read
                    time.sleep(0.5) # Debounce/allow card removal

            # Timer display logic
            if timer_running: # Only if timer is actively running
                current_ticks = time.ticks_ms()
                current_elapsed_ms = time.ticks_diff(current_ticks, timer_start_time)
                current_elapsed_sec = current_elapsed_ms // 1000
                if current_elapsed_sec != last_timer_print_sec:
                     print(f"Časovač beží: {current_elapsed_sec} sekúnd")
                     last_timer_print_sec = current_elapsed_sec
                # Potentially blink an LED slowly to indicate timer is running if desired
                # e.g., if not sending_in_progress: led1_pin.value(time.ticks_ms() // 500 % 2)

            time.sleep(0.05) # Main loop delay

    except KeyboardInterrupt:
        print("\nDetekované KeyboardInterrupt. Zastavuje sa program.")
    except Exception as e:
        print(f"\n!!! NEOČAKÁVANÁ CHYBA v hlavnej slučke: {type(e).__name__}: {e}")
        sys.print_exception(e)
        if vfs: # Try to log to SD card if available
            try:
                 with open(SD_MOUNT_POINT + "/error_log.txt","a") as f:
                      timestamp_tuple = time.localtime()
                      # Format: YYYY-MM-DD HH:MM:SS
                      timestamp_str = "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
                          timestamp_tuple[0], timestamp_tuple[1], timestamp_tuple[2],
                          timestamp_tuple[3], timestamp_tuple[4], timestamp_tuple[5]
                      )
                      f.write(f"{timestamp_str} - Chyba hlavnej slučky: {type(e).__name__}: {e}\n")
                      sys.print_exception(e, f) # Write full traceback to file
                 print("Podrobnosti o chybe zaznamenané do error_log.txt na SD karte.")
            except Exception as log_e:
                 print(f"Nepodarilo sa zapísať do chybového denníka na SD karte: {log_e}")
        # Halt with fast blinking LEDs to indicate critical error
        while True:
            led1_pin.value(1); led2_pin.value(1); time.sleep(0.1)
            led1_pin.value(0); led2_pin.value(0); time.sleep(0.1)

    finally:
        # Cleanup
        sending_in_progress = False # Ensure this is false on exit
        led1_pin.value(0)
        led2_pin.value(0)

        if sta.isconnected():
            print("Odpája sa Wi-Fi...")
            sta.disconnect(); time.sleep(1) # Give it a moment
        if sta.active():
             print("Deaktivuje sa Wi-Fi rozhranie..."); sta.active(False)

        try:
            if vfs:
                os.umount(SD_MOUNT_POINT)
                print("Odpojená SD karta.")
        except Exception as e:
            print(f"Chyba pri odpájaní SD karty: {e}")

        print("Program ukončený.")

# --- Spustenie hlavného programu ---
if __name__ == "__main__":
    main()
