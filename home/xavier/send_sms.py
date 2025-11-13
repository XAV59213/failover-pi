#!/usr/bin/env python3
import serial
import time
import sys
import json

CONFIG_FILE = "/home/xavier/config.json"

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

if len(sys.argv) < 2:
    print("Usage: python3 send_sms.py 'message'")
    sys.exit(1)

message = sys.argv[1]
config = load_config()
phone_number = config.get("sms_phone", "+33XXXXXXXXX")
serial_port = config.get("serial_port", "/dev/ttyUSB3")

ser = serial.Serial(
    port=serial_port,
    baudrate=115200,
    timeout=5
)

def send_at(cmd, expected='OK', timeout=5):
    ser.write((cmd + '\r\n').encode())
    time.sleep(timeout)
    response = ser.read_all().decode(errors='ignore')
    return expected in response

try:
    send_at('AT', 'OK', 1)
    if config.get("sim_pin"):
        send_at(f'AT+CPIN="{config["sim_pin"]}"', 'OK', 5)
    send_at('AT+CMGF=1', 'OK', 1)
    send_at(f'AT+CMGS="{phone_number}"', '>', 2)
    ser.write((message + chr(26)).encode())
    time.sleep(5)
    response = ser.read_all().decode(errors='ignore')
    if 'OK' in response:
        print("SMS envoyé !")
    else:
        print("Erreur :", response)
finally:
    ser.close()
