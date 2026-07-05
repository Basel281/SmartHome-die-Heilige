#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include <ESP32Servo.h>

//================ WIFI =================
const char* ssid = "Wokwi-GUEST";
const char* password = "";

//================ MQTT =================
const char* mqtt_server = "broker.hivemq.com";

// Eindeutiger Topic-Namespace für dieses Team
const char* baseTopic = "smarthome_die_Heiligen";

String ledGruenTopic  = String(baseTopic) + "/led_gruen";
String ledRotTopic    = String(baseTopic) + "/led_rot";
String ledWeissTopic  = String(baseTopic) + "/led_weiss";
String servoTopic     = String(baseTopic) + "/servo";

String tempTopic      = String(baseTopic) + "/temperature";
String humTopic       = String(baseTopic) + "/humidity";
String motionTopic    = String(baseTopic) + "/motion";

//================ PINS =================
// Pin-Zuordnung passend zur aktuellen diagram.json:
// GPIO25 = weiße LED, GPIO26 = rote LED, GPIO27 = grüne LED
#define LED_WEISS 25
#define LED_ROT   26
#define LED_GRUEN 27

#define BUTTON 4
#define PIR    14

#define DHTPIN  15
#define DHTTYPE DHT22

#define SERVOPIN 13

//================ OBJEKTE =================
DHT dht(DHTPIN, DHTTYPE);
Servo servo1;

WiFiClient espClient;
PubSubClient client(espClient);

//================ VARIABLEN =================
bool ledGruenState = true;    // grüne LED soll standardmäßig dauerhaft leuchten
bool ledRotState   = false;
bool ledWeissState = false;

bool lastButtonState = HIGH;
bool lastMotion = LOW;

unsigned long lastPublish = 0;

//================ MQTT CALLBACK =================
void callback(char* topic, byte* payload, unsigned int length) {

  String message = "";

  for (unsigned int i = 0; i < length; i++) {
    message += (char)payload[i];
  }

  String topicStr = String(topic);

  Serial.print("Topic: ");
  Serial.println(topicStr);

  Serial.print("Nachricht: ");
  Serial.println(message);

  // Weiße LED kann per Dashboard geschaltet werden
  if (topicStr == ledWeissTopic) {
    ledWeissState = (message == "ON");
    digitalWrite(LED_WEISS, ledWeissState);
  }

  if (topicStr == servoTopic) {
    int angle = message.toInt();
    angle = constrain(angle, 0, 180);
    servo1.write(angle);
  }
}

//================ SETUP =================
void setup() {

  Serial.begin(115200);

  pinMode(LED_GRUEN, OUTPUT);
  pinMode(LED_ROT, OUTPUT);
  pinMode(LED_WEISS, OUTPUT);

  pinMode(BUTTON, INPUT_PULLUP);
  pinMode(PIR, INPUT);

  // Grüne LED von Anfang an dauerhaft an, solange keine Bewegung erkannt wird
  digitalWrite(LED_GRUEN, HIGH);
  digitalWrite(LED_ROT, LOW);
  digitalWrite(LED_WEISS, LOW);

  dht.begin();

  servo1.attach(SERVOPIN);
  servo1.write(0);

  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.println("WiFi verbunden");

  client.setServer(mqtt_server, 1883);
  client.setCallback(callback);

  randomSeed(micros());
}

//================ MQTT RECONNECT =================
void reconnect() {

  while (!client.connected()) {

    Serial.print("Verbinde mit MQTT... ");

    String clientId = "SmartHomeDieHeiligen-" + String(random(0xffff), HEX);

    if (client.connect(clientId.c_str())) {

      Serial.println("Verbunden");

      client.subscribe(ledWeissTopic.c_str());
      client.subscribe(servoTopic.c_str());

      // aktuellen Zustand der weißen LED direkt nach Verbindung an alle
      // Abonnenten (z.B. Dashboard) senden, retained, damit neue Clients
      // sofort den korrekten Stand sehen
      client.publish(ledWeissTopic.c_str(), ledWeissState ? "ON" : "OFF", true);

    } else {

      Serial.print("Fehlgeschlagen, rc=");
      Serial.println(client.state());

      delay(2000);
    }
  }
}

//================ LOOP =================
void loop() {

  if (!client.connected()) {
    reconnect();
  }

  client.loop();

  // ---------- TASTER: schaltet die weiße LED ----------
  bool currentButton = digitalRead(BUTTON);

  if (lastButtonState == HIGH && currentButton == LOW) {

    ledWeissState = !ledWeissState;

    digitalWrite(LED_WEISS, ledWeissState);

    // retained publish, damit das Dashboard den Tasterdruck sofort übernimmt
    client.publish(ledWeissTopic.c_str(), ledWeissState ? "ON" : "OFF", true);

    delay(250);
  }

  lastButtonState = currentButton;

  // ---------- DHT22 ----------
  if (millis() - lastPublish > 5000) {

    lastPublish = millis();

    float t = dht.readTemperature();
    float h = dht.readHumidity();

    if (!isnan(t) && !isnan(h)) {

      String temp = String(t, 1);
      String hum = String(h, 1);

      client.publish(tempTopic.c_str(), temp.c_str());
      client.publish(humTopic.c_str(), hum.c_str());

      Serial.print("Temperatur: ");
      Serial.println(temp);

      Serial.print("Luftfeuchtigkeit: ");
      Serial.println(hum);
    }
  }

  // ---------- PIR: grün <-> rot ----------
  bool currentMotion = digitalRead(PIR);

  if (currentMotion != lastMotion) {

    lastMotion = currentMotion;

    if (currentMotion == HIGH) {

      // Bewegung erkannt: grün aus, rot an
      ledGruenState = false;
      ledRotState = true;
      digitalWrite(LED_GRUEN, LOW);
      digitalWrite(LED_ROT, HIGH);

      Serial.println("Bewegung erkannt");
      client.publish(motionTopic.c_str(), "MOTION");

    } else {

      // Keine Bewegung mehr: rot aus, grün wieder dauerhaft an
      ledGruenState = true;
      ledRotState = false;
      digitalWrite(LED_GRUEN, HIGH);
      digitalWrite(LED_ROT, LOW);

      Serial.println("Keine Bewegung");
      client.publish(motionTopic.c_str(), "NO_MOTION");

    }
  }
}
