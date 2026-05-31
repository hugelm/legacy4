import http.server
import json
import sqlite3
import os
import re
from datetime import datetime

# --- Database Setup ---
DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, 'legacyhub.db')

def get_db():
    """Get a new database connection with row_factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    """Initialize the database schema."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS devices (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            type        TEXT DEFAULT 'Custom IoT Device',
            ingress     TEXT DEFAULT 'API Ingestion',
            status      TEXT DEFAULT 'STANDBY',
            icon        TEXT DEFAULT 'fa-microchip',
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS telemetry (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id       TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            vibration_index REAL NOT NULL,
            status          TEXT DEFAULT 'RUNNING',
            timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS maintenance (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id   TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            title       TEXT NOT NULL,
            description TEXT,
            technician  TEXT,
            priority    TEXT DEFAULT 'routine',
            scheduled   TIMESTAMP NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_telemetry_device ON telemetry(device_id);
        CREATE INDEX IF NOT EXISTS idx_telemetry_timestamp ON telemetry(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_maintenance_device ON maintenance(device_id);
        CREATE INDEX IF NOT EXISTS idx_maintenance_scheduled ON maintenance(scheduled);
    """)

    conn.commit()
    conn.close()
    print("[DB] Database initialized at", DB_PATH, flush=True)


# --- HTTP Handler ---
class IoTInboundHandlerV3(http.server.BaseHTTPRequestHandler):

    def _send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _send_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode('utf-8'))

    def _read_body(self):
        content_length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(content_length)
        return json.loads(raw.decode('utf-8'))

    def _parse_path(self):
        """Parse path into segments, e.g. /api/v3/devices/abc -> ['api','v3','devices','abc']"""
        return [s for s in self.path.split('?')[0].split('/') if s]

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    # ==================== GET ====================
    def do_GET(self):
        segments = self._parse_path()

        # GET /api/v3/devices
        if segments == ['api', 'v3', 'devices']:
            self._get_devices()

        # GET /api/v3/telemetry
        elif segments == ['api', 'v3', 'telemetry']:
            self._get_telemetry()

        # GET /api/v3/maintenance
        elif segments == ['api', 'v3', 'maintenance']:
            self._get_maintenance()

        # GET /api/v3/dashboard
        elif segments == ['api', 'v3', 'dashboard']:
            self._get_dashboard()

        else:
            self._send_json(404, {"error": "Not found"})

    # ==================== POST ====================
    def do_POST(self):
        segments = self._parse_path()

        # POST /api/v3/devices
        if segments == ['api', 'v3', 'devices']:
            self._create_device()

        # POST /api/v3/telemetry
        elif segments == ['api', 'v3', 'telemetry']:
            self._create_telemetry()

        # POST /api/v3/maintenance
        elif segments == ['api', 'v3', 'maintenance']:
            self._create_maintenance()

        else:
            self._send_json(404, {"error": "Not found"})

    # ==================== PUT ====================
    def do_PUT(self):
        segments = self._parse_path()

        # PUT /api/v3/devices/{id}
        if len(segments) == 4 and segments[:3] == ['api', 'v3', 'devices']:
            self._update_device(segments[3])

        # PUT /api/v3/maintenance/{id}
        elif len(segments) == 4 and segments[:3] == ['api', 'v3', 'maintenance']:
            self._update_maintenance(segments[3])

        else:
            self._send_json(404, {"error": "Not found"})

    # ==================== DELETE ====================
    def do_DELETE(self):
        segments = self._parse_path()

        # DELETE /api/v3/devices/{id}
        if len(segments) == 4 and segments[:3] == ['api', 'v3', 'devices']:
            self._delete_device(segments[3])

        # DELETE /api/v3/maintenance/{id}
        elif len(segments) == 4 and segments[:3] == ['api', 'v3', 'maintenance']:
            self._delete_maintenance(segments[3])

        else:
            self._send_json(404, {"error": "Not found"})

    # ========== Device Handlers ==========

    def _get_devices(self):
        conn = get_db()
        rows = conn.execute("""
            SELECT d.*,
                   (SELECT COUNT(*) FROM telemetry t WHERE t.device_id = d.id) as telemetry_count,
                   (SELECT t.vibration_index FROM telemetry t WHERE t.device_id = d.id ORDER BY t.timestamp DESC LIMIT 1) as last_vibration,
                   (SELECT t.timestamp FROM telemetry t WHERE t.device_id = d.id ORDER BY t.timestamp DESC LIMIT 1) as last_seen
            FROM devices d
            ORDER BY d.created_at DESC
        """).fetchall()
        conn.close()
        self._send_json(200, [dict(r) for r in rows])

    def _create_device(self):
        try:
            body = self._read_body()
            device_id = body.get('id', '').strip()
            name = body.get('name', '').strip()

            if not device_id or not name:
                self._send_json(400, {"error": "Fields 'id' and 'name' are required"})
                return

            # Sanitize device_id: lowercase, alphanumeric + hyphens
            device_id = re.sub(r'[^a-z0-9\-]', '-', device_id.lower())

            conn = get_db()
            try:
                conn.execute("""
                    INSERT INTO devices (id, name, type, ingress, status, icon)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    device_id,
                    name,
                    body.get('type', 'Custom IoT Device'),
                    body.get('ingress', 'API Ingestion'),
                    body.get('status', 'STANDBY'),
                    body.get('icon', 'fa-microchip')
                ))
                conn.commit()
                print(f"[DEVICE-CREATED] {device_id} ({name})", flush=True)
                self._send_json(201, {"status": "CREATED", "device_id": device_id})
            except sqlite3.IntegrityError:
                self._send_json(409, {"error": f"Device '{device_id}' already exists"})
            finally:
                conn.close()

        except Exception as e:
            print(f"[ERROR] Create device failed: {e}", flush=True)
            self._send_json(400, {"error": str(e)})

    def _update_device(self, device_id):
        try:
            body = self._read_body()
            conn = get_db()

            # Check existence
            existing = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
            if not existing:
                conn.close()
                self._send_json(404, {"error": f"Device '{device_id}' not found"})
                return

            conn.execute("""
                UPDATE devices
                SET name = ?, type = ?, ingress = ?, status = ?, icon = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                body.get('name', existing['name']),
                body.get('type', existing['type']),
                body.get('ingress', existing['ingress']),
                body.get('status', existing['status']),
                body.get('icon', existing['icon']),
                device_id
            ))
            conn.commit()
            conn.close()
            print(f"[DEVICE-UPDATED] {device_id}", flush=True)
            self._send_json(200, {"status": "UPDATED", "device_id": device_id})

        except Exception as e:
            print(f"[ERROR] Update device failed: {e}", flush=True)
            self._send_json(400, {"error": str(e)})

    def _delete_device(self, device_id):
        conn = get_db()
        existing = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        if not existing:
            conn.close()
            self._send_json(404, {"error": f"Device '{device_id}' not found"})
            return

        conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
        conn.commit()
        conn.close()
        print(f"[DEVICE-DELETED] {device_id} (cascade: telemetry + maintenance)", flush=True)
        self._send_json(200, {"status": "DELETED", "device_id": device_id})

    # ========== Telemetry Handlers ==========

    def _get_telemetry(self):
        # Parse query params for device_id filter and limit
        query_string = self.path.split('?')[1] if '?' in self.path else ''
        params = dict(p.split('=') for p in query_string.split('&') if '=' in p)
        device_id = params.get('device_id', None)
        limit = int(params.get('limit', 50))

        conn = get_db()
        if device_id:
            rows = conn.execute("""
                SELECT t.*, d.name as device_name
                FROM telemetry t
                JOIN devices d ON t.device_id = d.id
                WHERE t.device_id = ?
                ORDER BY t.timestamp DESC LIMIT ?
            """, (device_id, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT t.*, d.name as device_name
                FROM telemetry t
                JOIN devices d ON t.device_id = d.id
                ORDER BY t.timestamp DESC LIMIT ?
            """, (limit,)).fetchall()
        conn.close()

        # Return in chronological order for charting
        result = [dict(r) for r in rows]
        result.reverse()
        self._send_json(200, result)

    def _create_telemetry(self):
        try:
            body = self._read_body()
            device_id = body.get('device_id', '').strip()
            vibration = float(body.get('vibration_index', 0.0))
            status = body.get('status', 'RUNNING')

            if not device_id:
                self._send_json(400, {"error": "Field 'device_id' is required"})
                return

            conn = get_db()

            # Check device exists
            device = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
            if not device:
                conn.close()
                self._send_json(404, {"error": f"Device '{device_id}' not found. Register it first."})
                return

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("""
                INSERT INTO telemetry (device_id, vibration_index, status, timestamp)
                VALUES (?, ?, ?, ?)
            """, (device_id, vibration, status, timestamp))

            # Also update device status
            conn.execute("""
                UPDATE devices SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
            """, (status, device_id))

            conn.commit()
            conn.close()

            print(f"[TELEMETRY] {device_id}: {vibration} mm/s ({status}) at {timestamp}", flush=True)
            self._send_json(200, {
                "status": "ACCEPTED",
                "device": device_id,
                "vibration_index": vibration,
                "timestamp": timestamp,
                "error": None
            })

        except Exception as e:
            print(f"[ERROR] Telemetry ingestion failed: {e}", flush=True)
            self._send_json(400, {"status": "REJECTED", "device": None, "error": str(e)})

    # ========== Maintenance Handlers ==========

    def _get_maintenance(self):
        conn = get_db()
        rows = conn.execute("""
            SELECT m.*, d.name as device_name
            FROM maintenance m
            JOIN devices d ON m.device_id = d.id
            ORDER BY m.scheduled ASC
        """).fetchall()
        conn.close()
        self._send_json(200, [dict(r) for r in rows])

    def _create_maintenance(self):
        try:
            body = self._read_body()
            device_id = body.get('device_id', '').strip()
            title = body.get('title', '').strip()
            scheduled = body.get('scheduled', '').strip()

            if not device_id or not title or not scheduled:
                self._send_json(400, {"error": "Fields 'device_id', 'title', and 'scheduled' are required"})
                return

            conn = get_db()

            # Check device exists
            device = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
            if not device:
                conn.close()
                self._send_json(404, {"error": f"Device '{device_id}' not found"})
                return

            cursor = conn.execute("""
                INSERT INTO maintenance (device_id, title, description, technician, priority, scheduled)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                device_id,
                title,
                body.get('description', ''),
                body.get('technician', ''),
                body.get('priority', 'routine'),
                scheduled
            ))
            conn.commit()
            new_id = cursor.lastrowid
            conn.close()

            print(f"[MAINTENANCE-CREATED] #{new_id} for {device_id}: {title}", flush=True)
            self._send_json(201, {"status": "CREATED", "id": new_id})

        except Exception as e:
            print(f"[ERROR] Create maintenance failed: {e}", flush=True)
            self._send_json(400, {"error": str(e)})

    def _update_maintenance(self, event_id):
        try:
            body = self._read_body()
            conn = get_db()

            existing = conn.execute("SELECT * FROM maintenance WHERE id = ?", (event_id,)).fetchone()
            if not existing:
                conn.close()
                self._send_json(404, {"error": f"Maintenance event #{event_id} not found"})
                return

            conn.execute("""
                UPDATE maintenance
                SET title = ?, description = ?, technician = ?, priority = ?, scheduled = ?, device_id = ?
                WHERE id = ?
            """, (
                body.get('title', existing['title']),
                body.get('description', existing['description']),
                body.get('technician', existing['technician']),
                body.get('priority', existing['priority']),
                body.get('scheduled', existing['scheduled']),
                body.get('device_id', existing['device_id']),
                event_id
            ))
            conn.commit()
            conn.close()
            print(f"[MAINTENANCE-UPDATED] #{event_id}", flush=True)
            self._send_json(200, {"status": "UPDATED", "id": int(event_id)})

        except Exception as e:
            print(f"[ERROR] Update maintenance failed: {e}", flush=True)
            self._send_json(400, {"error": str(e)})

    def _delete_maintenance(self, event_id):
        conn = get_db()
        existing = conn.execute("SELECT * FROM maintenance WHERE id = ?", (event_id,)).fetchone()
        if not existing:
            conn.close()
            self._send_json(404, {"error": f"Maintenance event #{event_id} not found"})
            return

        conn.execute("DELETE FROM maintenance WHERE id = ?", (event_id,))
        conn.commit()
        conn.close()
        print(f"[MAINTENANCE-DELETED] #{event_id}", flush=True)
        self._send_json(200, {"status": "DELETED", "id": int(event_id)})

    # ========== Dashboard Aggregate ==========

    def _get_dashboard(self):
        conn = get_db()

        # Device counts
        total_devices = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
        active_devices = conn.execute("SELECT COUNT(*) FROM devices WHERE status = 'RUNNING'").fetchone()[0]
        standby_devices = conn.execute("SELECT COUNT(*) FROM devices WHERE status = 'STANDBY'").fetchone()[0]

        # Telemetry stats
        total_telemetry = conn.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]
        avg_vibration = conn.execute("SELECT AVG(vibration_index) FROM telemetry").fetchone()[0]
        avg_vibration = round(avg_vibration, 2) if avg_vibration else 0.0

        # Recent telemetry for chart (last 30 entries)
        recent = conn.execute("""
            SELECT t.vibration_index, t.timestamp, t.device_id, d.name as device_name
            FROM telemetry t
            JOIN devices d ON t.device_id = d.id
            ORDER BY t.timestamp DESC LIMIT 30
        """).fetchall()
        history = [dict(r) for r in recent]
        history.reverse()

        # Upcoming maintenance
        upcoming_maintenance = conn.execute("""
            SELECT m.*, d.name as device_name
            FROM maintenance m
            JOIN devices d ON m.device_id = d.id
            ORDER BY m.scheduled ASC LIMIT 5
        """).fetchall()
        maintenance_list = [dict(r) for r in upcoming_maintenance]

        # Pending maintenance count
        pending_maintenance = conn.execute("SELECT COUNT(*) FROM maintenance").fetchone()[0]

        conn.close()

        self._send_json(200, {
            "total_devices": total_devices,
            "active_devices": active_devices,
            "standby_devices": standby_devices,
            "total_telemetry": total_telemetry,
            "avg_vibration": avg_vibration,
            "pending_maintenance": pending_maintenance,
            "history": history,
            "upcoming_maintenance": maintenance_list
        })

    def log_message(self, format, *args):
        """Override to add timestamp prefix."""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}", flush=True)


# --- Main ---
if __name__ == '__main__':
    init_db()
    server = http.server.HTTPServer(('0.0.0.0', 8082), IoTInboundHandlerV3)
    print("=" * 60, flush=True)
    print("  LegacyHub API v3 (SQLite) running on Port 8082", flush=True)
    print(f"  Database: {DB_PATH}", flush=True)
    print("=" * 60, flush=True)
    server.serve_forever()
