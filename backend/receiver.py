import http.server
import json

class IoTInboundHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/api/telemetry":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            try:
                payload = json.loads(post_data.decode('utf-8'))
                device_id = payload.get('device_id', 'UNKNOWN-DEVICE')
                vibration = payload.get('vibration_index', 0.0)

                print(f"[API-SUCCESS] Ingested from {device_id} ({vibration} mm/s)", flush=True)
                response = {"status": "ACCEPTED", "device": device_id, "error": None}
                self.wfile.write(json.dumps(response).encode('utf-8'))

            except Exception as e:
                print(f"[API-ERROR] Parsing failed: {str(e)}", flush=True)
                response = {"status": "REJECTED", "device": None, "error": f"Malformed JSON: {str(e)}"}
                self.wfile.write(json.dumps(response).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

server = http.server.HTTPServer(('0.0.0.0', 8080), IoTInboundHandler)
print("Python API microservice engine running on Port 8080...", flush=True)
server.serve_forever()