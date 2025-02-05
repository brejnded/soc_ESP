# s3_bridge.py (ESP32 S3 Mini - Bridge Code - Version 5 - UART1 - WITH SOCKET SERVER)
import network
import time
import machine
import socket
import ujson # For MicroPython JSON

# --- Serial Configuration (UART1) ---
uart = machine.UART(1, baudrate=115200, tx=machine.Pin(43), rx=machine.Pin(44))
print("UART1 initialized")

# --- Set up Access Point (Simplified) ---
ap = network.WLAN(network.AP_IF)
print("Activating AP interface...")
ap_active_result = ap.active(True)
print("AP interface active (after activation):", ap_active_result)

if not ap_active_result:
    print("Error activating AP. Check for preceding errors.")
else:
    print("No immediate error during AP activation.")

time.sleep(1) # Keep delay for initial setup

print("Configuring AP...")
try:
    ap.config(essid="MyESP32S3AP", password="yourpassword", channel=6, authmode=network.AUTH_WPA_WPA2_PSK) # Use a simple SSID/password for testing
    print("AP configuration set.")
except OSError as e:
    print("Error configuring AP:", e)
    if e.args[0] == -259:
        print("OSError -259: ESP_ERR_INVALID_STATE. Wi-Fi state issue during CONFIG.")
    else:
        print("Other OSError during AP config.")

while not ap.active():
    print("Waiting for AP to become active...")
    time.sleep(0.5)

print("AP created. IP:", ap.ifconfig()[0])
server_ip = ap.ifconfig()[0] # Get the AP IP
server_port = 80

# --- Socket Server ---
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind((server_ip, server_port))
s.listen(1)
print(f"Socket server listening on {server_ip}:{server_port}")

while True:
    conn, addr = s.accept()
    print('Got a connection from %s' % str(addr))
    request = conn.recv(1024)
    request_str = request.decode('utf-8')
    print("Received Request:\n", request_str) # Print the raw request

    if request_str.startswith("POST /add"): # Check if it's a POST to /add (like client.py sends)
        try:
            content_start = request_str.find('\r\n\r\n') + 4 # Find the start of the content
            if content_start > 4:
                json_payload_str = request_str[content_start:]
                print("Extracted JSON Payload:\n", json_payload_str) # Print extracted JSON string
                try:
                    json_payload = ujson.loads(json_payload_str) # Parse JSON (use ujson for MicroPython)
                    print("Parsed JSON Payload:", json_payload) # Print parsed JSON

                    # Forward the JSON data over UART. You can send the JSON string directly.
                    uart.write(json_payload_str + '\n') # Add newline for easier parsing on PC side if needed
                    print("JSON data forwarded over UART.")

                    response = "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nData received and forwarded via UART.\r\n"
                except ValueError as e_json:
                    print(f"Error parsing JSON: {e_json}")
                    response = "HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nInvalid JSON payload.\r\n"
            else:
                print("No content found in POST request.")
                response = "HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nNo POST data found.\r\n"

        except Exception as e_process:
            print(f"Error processing request: {e_process}")
            response = "HTTP/1.1 500 Internal Server Error\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nError processing request.\r\n"
    else:
        response = "HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nNot Found.\r\n"

    conn.sendall(response.encode('utf-8'))
    conn.close()