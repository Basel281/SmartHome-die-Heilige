"""
Smart-Home Gestensteuerung
==========================
Projekt: smarthome_die_Heiligen

Erkennt Handgesten über die Webcam mit MediaPipe und steuert per MQTT
den Servo (Rollo) und die weiße LED (Licht) des ESP32.

Gesten -> Aktion:
  Daumen hoch   (Thumb_Up)    -> Rollo hoch / offen   (servo -> 0)
  Daumen runter (Thumb_Down)  -> Rollo runter / zu     (servo -> 180)
  Offene Hand   (Open_Palm)   -> Licht an               (led_weiss -> ON)
  Faust         (Closed_Fist) -> Licht aus              (led_weiss -> OFF)

Voraussetzungen:
  pip install mediapipe opencv-python paho-mqtt

Modell:
  Beim ersten Start wird "gesture_recognizer.task" automatisch von
  Google heruntergeladen, falls es noch nicht im selben Ordner liegt.
"""

import os
import time
import urllib.request

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
import paho.mqtt.client as mqtt

# ================= KONFIGURATION =================

BASE_TOPIC = "smarthome_die_Heiligen"

TOPIC_SERVO      = f"{BASE_TOPIC}/servo"
TOPIC_LED_WEISS  = f"{BASE_TOPIC}/led_weiss"

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT   = 1883
MQTT_CLIENT_ID = "GestureControl_" + BASE_TOPIC

MODEL_PATH = "gesture_recognizer.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task"
)

# Geste muss so viele Frames am Stück erkannt werden, bevor sie ausgelöst wird
# (verhindert Fehlauslösungen durch Flackern)
STABLE_FRAMES_REQUIRED = 6

# Mindestabstand zwischen zwei MQTT-Befehlen derselben Geste (Sekunden)
COOLDOWN_SECONDS = 1.5

# Gesten -> (Topic, Payload, Anzeigetext)
GESTURE_ACTIONS = {
    "Thumb_Up":    (TOPIC_SERVO,     "0",   "Rollo hoch"),
    "Thumb_Down":  (TOPIC_SERVO,     "180", "Rollo runter"),
    "Open_Palm":   (TOPIC_LED_WEISS, "ON",  "Licht an"),
    "Closed_Fist": (TOPIC_LED_WEISS, "OFF", "Licht aus"),
}

# ================= MQTT SETUP =================

# paho-mqtt 2.x verlangt callback_api_version explizit, ältere Versionen (1.x)
# kennen dieses Argument nicht -> mit Fallback abfangen
try:
    client = mqtt.Client(
        client_id=MQTT_CLIENT_ID,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
    )
except AttributeError:
    # paho-mqtt < 2.0 installiert
    client = mqtt.Client(client_id=MQTT_CLIENT_ID)


def on_connect(c, userdata, flags, rc):
    if rc == 0:
        print("MQTT verbunden mit", MQTT_BROKER)
    else:
        print("MQTT Verbindung fehlgeschlagen, rc =", rc)


def on_disconnect(c, userdata, rc):
    print("MQTT getrennt, rc =", rc)


def on_publish(c, userdata, mid):
    print(f"[MQTT] Nachricht {mid} erfolgreich gesendet")


client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_publish = on_publish

print(f"Verbinde mit {MQTT_BROKER}:{MQTT_PORT} ...")
client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
client.loop_start()

# kurz warten, damit die Verbindung sicher steht, bevor die Kamera startet
time.sleep(1)


def send_command(gesture_name):
    if gesture_name not in GESTURE_ACTIONS:
        return
    topic, payload, label = GESTURE_ACTIONS[gesture_name]
    result = client.publish(topic, payload, retain=True)
    print(f"[GESTE] {label} erkannt -> publiziere {topic} = {payload} (rc={result.rc})")


# ================= MODELL LADEN (bei Bedarf herunterladen) =================

if not os.path.exists(MODEL_PATH):
    print("Lade Gesture-Recognizer-Modell herunter...")
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    print("Modell gespeichert als", MODEL_PATH)

base_options = mp_python.BaseOptions(model_asset_path=MODEL_PATH)
options = vision.GestureRecognizerOptions(
    base_options=base_options,
    running_mode=vision.RunningMode.VIDEO,
    num_hands=1,
)
recognizer = vision.GestureRecognizer.create_from_options(options)

# ================= KAMERA-LOOP =================

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    raise RuntimeError("Webcam konnte nicht geöffnet werden")

last_gesture = None
stable_count = 0
last_sent_time = {}

print("Gestensteuerung läuft. 'q' zum Beenden drücken.")

frame_timestamp_ms = 0

while True:
    ok, frame = cap.read()
    if not ok:
        break

    frame = cv2.flip(frame, 1)
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

    frame_timestamp_ms += 33  # ~30 fps Annahme
    result = recognizer.recognize_for_video(mp_image, frame_timestamp_ms)

    current_gesture = None
    if result.gestures:
        top = result.gestures[0][0]
        if top.score > 0.6:
            current_gesture = top.category_name

    # Stabilitätsprüfung: Geste muss mehrere Frames gleich bleiben
    if current_gesture == last_gesture:
        stable_count += 1
    else:
        stable_count = 0
        last_gesture = current_gesture

    display_text = current_gesture if current_gesture else "..."

    if (
        current_gesture in GESTURE_ACTIONS
        and stable_count == STABLE_FRAMES_REQUIRED
    ):
        now = time.time()
        last_time = last_sent_time.get(current_gesture, 0)
        if now - last_time > COOLDOWN_SECONDS:
            send_command(current_gesture)
            last_sent_time[current_gesture] = now

    # ---------- Anzeige ----------
    cv2.putText(
        frame, display_text, (20, 50),
        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3
    )
    cv2.imshow("Smart Home Gestensteuerung", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
client.loop_stop()
client.disconnect()
