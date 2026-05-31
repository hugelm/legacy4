import http.server
import json
import time
from datetime import datetime

# Global in-memory storage
telemetry_history = [
    {"device_id": "connector-alpha-4", "vibration_index": 3.5, "status": "RUNNING", "timestamp": "22:50:05"},
    {"device_id": "connector-alpha-4", "vibration_index": 4.1, "status": "RUNNING", "timestamp": "22:50:15"},
    {"device_id": "connector-alpha-4", "vibration_index": 3.8, "status": "RUNNING", "timestamp": "22:50:25"},
    {"device_id": "connector-alpha-4", "vibration_index": 4.6, "status": "RUNNING", "timestamp": "22:50:35"},
    {"device_id": "connector-alpha-4", "vibration_index": 5.23, "status": "RUNNING", "timestamp": "22:50:45"},
    {"device_id": "connector-alpha-4", "vibration_index": 4.8, "status": "RUNNING", "timestamp": "22:50:55"},
    {"device_id": "connector-alpha-4", "vibration_index": 3.9, "status": "RUNNING", "timestamp": "22:51:05"},
    {"device_id": "connector-alpha-4", "vibration_index": 4.3, "status": "RUNNING", "timestamp": "22:51:15"},
    {"device_id": "connector-alpha-4", "vibration_index": 5.0, "status": "RUNNING", "timestamp": "22:51:25"},
    {"device_id": "connector-alpha-4", "vibration_index": 4.7, "status": "RUNNING", "timestamp": "22:51:35"},
    {"device_id": "connector-alpha-4", "vibration_index": 5.23, "status": "RUNNING", "timestamp": "22:51:45"},
    {"device_id": "connector-alpha-4", "vibration_index": 5.1, "status": "RUNNING", "timestamp": "22:51:55"},
]

devices_status = {
    "connector-alpha-4": {"vibration_index": 5.1, "status": "RUNNING", "last_seen": "22:51:55", "type": "Modbus RTU Bridge", "ingress": "NGINX Reverse Proxy"},
    "compressor-gamma-2": {"vibration_index": 2.11, "status": "RUNNING", "last_seen": "22:51:30", "type": "OPC-UA Embedded Link", "ingress": "Direct Backend Node"},
    "grid-node-beta-9": {"vibration_index": 0.00, "status": "STANDBY", "last_seen": "22:50:12", "type": "EtherNet/IP Gateway", "ingress": "Direct Backend Node"}
}

class IoTInboundHandlerV2(http.server.BaseHTTPRequestHandler):
    def _send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/telemetry":
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self._send_cors_headers()
            self.end_headers()

            # Compile dashboard dynamic state
            active_count = sum(1 for d in devices_status.values() if d.get("status") == "RUNNING")
            state_payload = {
                "history": telemetry_history,
                "devices": devices_status,
                "total_connected": len(devices_status),
                "active_connected": active_count
            }
            self.wfile.write(json.dumps(state_payload).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/telemetry":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self._send_cors_headers()
            self.end_headers()

            timestamp = datetime.now().strftime("%H:%M:%S")

            try:
                payload = json.loads(post_data.decode('utf-8'))
                device_id = payload.get('device_id', 'UNKNOWN-DEVICE')
                vibration = payload.get('vibration_index', 0.0)
                status = payload.get('status', 'RUNNING')

                # Update in-memory structures
                new_entry = {
                    "device_id": device_id,
                    "vibration_index": vibration,
                    "status": status,
                    "timestamp": timestamp
                }
                
                # Append to history, limit to last 50
                telemetry_history.append(new_entry)
                if len(telemetry_history) > 50:
                    telemetry_history.pop(0)

                # Update or register device status
                devices_status[device_id] = {
                    "vibration_index": vibration,
                    "status": status,
                    "last_seen": timestamp,
                    "type": payload.get('type', devices_status.get(device_id, {}).get('type', 'Custom IoT Device')),
                    "ingress": payload.get('ingress', devices_status.get(device_id, {}).get('ingress', 'API Ingestion'))
                }

                print(f"[API-SUCCESS-V2] Ingested from {device_id} ({vibration} mm/s) at {timestamp}", flush=True)
                response = {"status": "ACCEPTED", "device": device_id, "error": None}
                self.wfile.write(json.dumps(response).encode('utf-8'))

            except Exception as e:
                print(f"[API-ERROR-V2] Parsing failed: {str(e)}", flush=True)
                response = {"status": "REJECTED", "device": None, "error": f"Malformed JSON: {str(e)}"}
                self.wfile.write(json.dumps(response).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == '__main__':
    server = http.server.HTTPServer(('0.0.0.0', 8081), IoTInboundHandlerV2)
    print("Python API v2 microservice engine running on Port 8081...", flush=True)
    server.serve_forever()
