import http.server
import json
import pymysql
import pymysql.cursors
import os
import re
import sys
import time
from datetime import datetime

# --- Database Credentials from Environment ---
DB_HOST = os.environ.get('DB_HOST', 'db3')
DB_USER = os.environ.get('DB_USER', 'legacy_user')
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'legacy_pass')
DB_NAME = os.environ.get('DB_NAME', 'legacyhub')

def get_db():
    """Get a new database connection returning dict cursor."""
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )

def init_db():
    """Initialize the database schema and seed data with retry logic."""
    print("[DB] Initializing database...", flush=True)
    retries = 30
    conn = None
    while retries > 0:
        try:
            # First connect to host to create database if not exists
            conn = pymysql.connect(
                host=DB_HOST,
                user=DB_USER,
                password=DB_PASSWORD,
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=True
            )
            break
        except Exception as e:
            print(f"[DB] Connection failed: {e}. Retrying in 2 seconds... ({retries} retries left)", flush=True)
            time.sleep(2)
            retries -= 1

    if not conn:
        print("[DB] Could not connect to database host. Exiting.", flush=True)
        sys.exit(1)

    try:
        with conn.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}")
        conn.select_db(DB_NAME)

        with conn.cursor() as cursor:
            # Create devices table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS devices (
                    id          VARCHAR(100) PRIMARY KEY,
                    name        VARCHAR(255) NOT NULL,
                    type        VARCHAR(100) DEFAULT 'Custom IoT Device',
                    ingress     VARCHAR(100) DEFAULT 'API Ingestion',
                    status      VARCHAR(50) DEFAULT 'STANDBY',
                    icon        VARCHAR(100) DEFAULT 'fa-microchip',
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # Create telemetry table with extra fields
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS telemetry (
                    id                  INT AUTO_INCREMENT PRIMARY KEY,
                    device_id           VARCHAR(100) NOT NULL,
                    vibration_index     DOUBLE NOT NULL,
                    temperature         DOUBLE DEFAULT 0.0,
                    power_consumption_kw DOUBLE DEFAULT 0.0,
                    operating_hours     DOUBLE DEFAULT 0.0,
                    status              VARCHAR(50) DEFAULT 'RUNNING',
                    timestamp           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # Create maintenance table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS maintenance (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    device_id   VARCHAR(100) NOT NULL,
                    title       VARCHAR(255) NOT NULL,
                    description TEXT,
                    technician  VARCHAR(255),
                    priority    VARCHAR(50) DEFAULT 'routine',
                    scheduled   TIMESTAMP NOT NULL,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # Create indexes (ignore if they already exist)
            try:
                cursor.execute("CREATE INDEX idx_telemetry_device ON telemetry(device_id)")
            except Exception: pass
            try:
                cursor.execute("CREATE INDEX idx_telemetry_timestamp ON telemetry(timestamp DESC)")
            except Exception: pass
            try:
                cursor.execute("CREATE INDEX idx_maintenance_device ON maintenance(device_id)")
            except Exception: pass
            try:
                cursor.execute("CREATE INDEX idx_maintenance_scheduled ON maintenance(scheduled)")
            except Exception: pass

            # Seed default data if devices table is empty
            cursor.execute("SELECT COUNT(*) as count FROM devices")
            device_count = cursor.fetchone()['count']

            if device_count == 0:
                print("[DB] Database is empty. Seeding sample datasets...", flush=True)

                # Seed devices
                default_devices = [
                    ('pump-alpha-01', 'Pump Alpha-01', 'Custom IoT Device', 'API Ingestion', 'RUNNING', 'fa-fan'),
                    ('turbine-beta-02', 'Turbine Beta-02', 'OPC-UA Embedded Link', 'Edge Gateway', 'STANDBY', 'fa-bolt'),
                    ('compressor-gamma-03', 'Compressor Gamma-03', 'Modbus RTU Bridge', 'Direct Backend Node', 'OFFLINE', 'fa-server')
                ]
                cursor.executemany("""
                    INSERT INTO devices (id, name, type, ingress, status, icon)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, default_devices)

                # Seed telemetry history
                base_time = datetime.now()
                telemetry_data = []
                for i in range(15):
                    # Offsets in 5 minutes intervals going backwards
                    ts = (base_time - pymysql.converters.timedelta(minutes=(15 - i) * 5)).strftime("%Y-%m-%d %H:%M:%S")
                    
                    # Pump Alpha-01
                    telemetry_data.append((
                        'pump-alpha-01',
                        float(round(4.0 + (i % 3) * 0.4 + (i % 2) * 0.2, 2)), # vibration
                        float(round(60.0 + i * 0.8, 1)),                      # temp
                        float(round(11.5 + (i % 4) * 0.5, 2)),                # power
                        float(round(230.5 + i * 0.08, 2)),                    # operating hours
                        'RUNNING',
                        ts
                    ))
                    # Turbine Beta-02
                    telemetry_data.append((
                        'turbine-beta-02',
                        float(round(1.2 + (i % 2) * 0.2, 2)),
                        float(round(42.5 + i * 0.3, 1)),
                        float(round(5.2 + (i % 3) * 0.1, 2)),
                        float(round(884.0 + i * 0.08, 2)),
                        'STANDBY',
                        ts
                    ))

                cursor.executemany("""
                    INSERT INTO telemetry (device_id, vibration_index, temperature, power_consumption_kw, operating_hours, status, timestamp)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, telemetry_data)

                # Seed maintenance events
                maint_events = [
                    ('pump-alpha-01', 'Scheduled Calibration', 'Routine sensor re-calibration.', 'John D.', 'routine', (base_time + pymysql.converters.timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")),
                    ('turbine-beta-02', 'Filter Replacement', 'Replace air intake and cooling filters.', 'Alice S.', 'medium', (base_time + pymysql.converters.timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")),
                    ('compressor-gamma-03', 'Emergency Bearing Check', 'Address high vibration warnings.', 'Bob K.', 'immediate', (base_time + pymysql.converters.timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S"))
                ]
                cursor.executemany("""
                    INSERT INTO maintenance (device_id, title, description, technician, priority, scheduled)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, maint_events)

                print("[DB] Seeding completed.", flush=True)

        conn.commit()
        print("[DB] Database initialized successfully.", flush=True)
    except Exception as e:
        print(f"[DB] Error creating tables / seeding: {e}", flush=True)
        sys.exit(1)
    finally:
        conn.close()


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

    def _send_error(self, status_code, error_message):
        """Standardized JSON error formatting."""
        self._send_json(status_code, {
            "success": False,
            "status": "ERROR",
            "error": error_message,
            "code": status_code
        })

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

        if segments == ['api', 'v3', 'devices']:
            self._get_devices()
        elif segments == ['api', 'v3', 'telemetry']:
            self._get_telemetry()
        elif segments == ['api', 'v3', 'maintenance']:
            self._get_maintenance()
        elif segments == ['api', 'v3', 'dashboard']:
            self._get_dashboard()
        else:
            self._send_error(404, "Endpoint not found")

    # ==================== POST ====================
    def do_POST(self):
        segments = self._parse_path()

        if segments == ['api', 'v3', 'devices']:
            self._create_device()
        elif segments == ['api', 'v3', 'telemetry']:
            self._create_telemetry()
        elif segments == ['api', 'v3', 'maintenance']:
            self._create_maintenance()
        else:
            self._send_error(404, "Endpoint not found")

    # ==================== PUT ====================
    def do_PUT(self):
        segments = self._parse_path()

        if len(segments) == 4 and segments[:3] == ['api', 'v3', 'devices']:
            self._update_device(segments[3])
        elif len(segments) == 4 and segments[:3] == ['api', 'v3', 'maintenance']:
            self._update_maintenance(segments[3])
        else:
            self._send_error(404, "Endpoint not found")

    # ==================== DELETE ====================
    def do_DELETE(self):
        segments = self._parse_path()

        if len(segments) == 4 and segments[:3] == ['api', 'v3', 'devices']:
            self._delete_device(segments[3])
        elif len(segments) == 4 and segments[:3] == ['api', 'v3', 'maintenance']:
            self._delete_maintenance(segments[3])
        else:
            self._send_error(404, "Endpoint not found")

    # ========== Device Handlers ==========

    def _get_devices(self):
        try:
            conn = get_db()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT d.*,
                           (SELECT COUNT(*) FROM telemetry t WHERE t.device_id = d.id) as telemetry_count,
                           (SELECT t.vibration_index FROM telemetry t WHERE t.device_id = d.id ORDER BY t.timestamp DESC LIMIT 1) as last_vibration,
                           (SELECT t.timestamp FROM telemetry t WHERE t.device_id = d.id ORDER BY t.timestamp DESC LIMIT 1) as last_seen
                    FROM devices d
                    ORDER BY d.created_at DESC
                """)
                rows = cursor.fetchall()
            conn.close()
            self._send_json(200, rows)
        except Exception as e:
            self._send_error(500, f"Database query failed: {str(e)}")

    def _create_device(self):
        try:
            body = self._read_body()
            device_id = body.get('id', '').strip()
            name = body.get('name', '').strip()

            if not device_id or not name:
                self._send_error(400, "Fields 'id' and 'name' are required")
                return

            device_id = re.sub(r'[^a-z0-9\-]', '-', device_id.lower())

            conn = get_db()
            try:
                with conn.cursor() as cursor:
                    # Check if exists first
                    cursor.execute("SELECT * FROM devices WHERE id = %s", (device_id,))
                    if cursor.fetchone():
                        self._send_error(409, f"Device '{device_id}' already exists")
                        return

                    cursor.execute("""
                        INSERT INTO devices (id, name, type, ingress, status, icon)
                        VALUES (%s, %s, %s, %s, %s, %s)
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
            finally:
                conn.close()

        except Exception as e:
            print(f"[ERROR] Create device failed: {e}", flush=True)
            self._send_error(400, str(e))

    def _update_device(self, device_id):
        try:
            body = self._read_body()
            conn = get_db()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM devices WHERE id = %s", (device_id,))
                    existing = cursor.fetchone()
                    if not existing:
                        self._send_error(404, f"Device '{device_id}' not found")
                        return

                    cursor.execute("""
                        UPDATE devices
                        SET name = %s, type = %s, ingress = %s, status = %s, icon = %s
                        WHERE id = %s
                    """, (
                        body.get('name', existing['name']),
                        body.get('type', existing['type']),
                        body.get('ingress', existing['ingress']),
                        body.get('status', existing['status']),
                        body.get('icon', existing['icon']),
                        device_id
                    ))
                conn.commit()
                print(f"[DEVICE-UPDATED] {device_id}", flush=True)
                self._send_json(200, {"status": "UPDATED", "device_id": device_id})
            finally:
                conn.close()

        except Exception as e:
            print(f"[ERROR] Update device failed: {e}", flush=True)
            self._send_error(400, str(e))

    def _delete_device(self, device_id):
        try:
            conn = get_db()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM devices WHERE id = %s", (device_id,))
                    existing = cursor.fetchone()
                    if not existing:
                        self._send_error(404, f"Device '{device_id}' not found")
                        return

                    cursor.execute("DELETE FROM devices WHERE id = %s", (device_id,))
                conn.commit()
                print(f"[DEVICE-DELETED] {device_id} (cascade: telemetry + maintenance)", flush=True)
                self._send_json(200, {"status": "DELETED", "device_id": device_id})
            finally:
                conn.close()
        except Exception as e:
            self._send_error(500, str(e))

    # ========== Telemetry Handlers ==========

    def _get_telemetry(self):
        try:
            query_string = self.path.split('?')[1] if '?' in self.path else ''
            params = dict(p.split('=') for p in query_string.split('&') if '=' in p)
            device_id = params.get('device_id', None)
            limit = int(params.get('limit', 50))

            conn = get_db()
            try:
                with conn.cursor() as cursor:
                    if device_id:
                        cursor.execute("""
                            SELECT t.*, d.name as device_name
                            FROM telemetry t
                            JOIN devices d ON t.device_id = d.id
                            WHERE t.device_id = %s
                            ORDER BY t.timestamp DESC LIMIT %s
                        """, (device_id, limit))
                    else:
                        cursor.execute("""
                            SELECT t.*, d.name as device_name
                            FROM telemetry t
                            JOIN devices d ON t.device_id = d.id
                            ORDER BY t.timestamp DESC LIMIT %s
                        """, (limit,))
                    rows = cursor.fetchall()
            finally:
                conn.close()

            result = list(rows)
            result.reverse()
            self._send_json(200, result)
        except Exception as e:
            self._send_error(500, str(e))

    def _create_telemetry(self):
        try:
            body = self._read_body()
            device_id = body.get('device_id', '').strip()
            vibration = float(body.get('vibration_index', 0.0))
            temperature = float(body.get('temperature', 0.0))
            power_consumption_kw = float(body.get('power_consumption_kw', 0.0))
            operating_hours = float(body.get('operating_hours', 0.0))
            status = body.get('status', 'RUNNING')

            if not device_id:
                self._send_error(400, "Field 'device_id' is required")
                return

            conn = get_db()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM devices WHERE id = %s", (device_id,))
                    device = cursor.fetchone()
                    if not device:
                        self._send_error(404, f"Device '{device_id}' not found. Register it first.")
                        return

                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute("""
                        INSERT INTO telemetry (device_id, vibration_index, temperature, power_consumption_kw, operating_hours, status, timestamp)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (device_id, vibration, temperature, power_consumption_kw, operating_hours, status, timestamp))

                    cursor.execute("""
                        UPDATE devices SET status = %s WHERE id = %s
                    """, (status, device_id))
                conn.commit()
            finally:
                conn.close()

            print(f"[TELEMETRY] {device_id}: {vibration} mm/s, {temperature} C, {power_consumption_kw} kW, {operating_hours} h ({status}) at {timestamp}", flush=True)
            self._send_json(200, {
                "status": "ACCEPTED",
                "device": device_id,
                "vibration_index": vibration,
                "temperature": temperature,
                "power_consumption_kw": power_consumption_kw,
                "operating_hours": operating_hours,
                "timestamp": timestamp,
                "error": None
            })

        except Exception as e:
            print(f"[ERROR] Telemetry ingestion failed: {e}", flush=True)
            self._send_error(400, str(e))

    # ========== Maintenance Handlers ==========

    def _get_maintenance(self):
        try:
            conn = get_db()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT m.*, d.name as device_name
                        FROM maintenance m
                        JOIN devices d ON m.device_id = d.id
                        ORDER BY m.scheduled ASC
                    """)
                    rows = cursor.fetchall()
            finally:
                conn.close()
            self._send_json(200, rows)
        except Exception as e:
            self._send_error(500, str(e))

    def _create_maintenance(self):
        try:
            body = self._read_body()
            device_id = body.get('device_id', '').strip()
            title = body.get('title', '').strip()
            scheduled = body.get('scheduled', '').strip()

            if not device_id or not title or not scheduled:
                self._send_error(400, "Fields 'device_id', 'title', and 'scheduled' are required")
                return

            try:
                scheduled_cleaned = scheduled.replace('T', ' ').split('.')[0].replace('Z', '')
                dt = datetime.strptime(scheduled_cleaned, "%Y-%m-%d %H:%M:%S")
            except Exception:
                try:
                    dt = datetime.strptime(scheduled, "%Y-%m-%d %H:%M")
                except Exception:
                    dt = datetime.fromisoformat(scheduled.replace('Z', '+00:00'))
            
            scheduled_db = dt.strftime("%Y-%m-%d %H:%M:%S")

            conn = get_db()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM devices WHERE id = %s", (device_id,))
                    device = cursor.fetchone()
                    if not device:
                        self._send_error(404, f"Device '{device_id}' not found")
                        return

                    cursor.execute("""
                        INSERT INTO maintenance (device_id, title, description, technician, priority, scheduled)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (
                        device_id,
                        title,
                        body.get('description', ''),
                        body.get('technician', ''),
                        body.get('priority', 'routine'),
                        scheduled_db
                    ))
                    new_id = cursor.lastrowid
                conn.commit()
            finally:
                conn.close()

            print(f"[MAINTENANCE-CREATED] #{new_id} for {device_id}: {title}", flush=True)
            self._send_json(201, {"status": "CREATED", "id": new_id})

        except Exception as e:
            print(f"[ERROR] Create maintenance failed: {e}", flush=True)
            self._send_error(400, str(e))

    def _update_maintenance(self, event_id):
        try:
            body = self._read_body()
            conn = get_db()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM maintenance WHERE id = %s", (event_id,))
                    existing = cursor.fetchone()
                    if not existing:
                        self._send_error(404, f"Maintenance event #{event_id} not found")
                        return

                    scheduled = body.get('scheduled', existing['scheduled'])
                    if isinstance(scheduled, str):
                        try:
                            scheduled_cleaned = scheduled.replace('T', ' ').split('.')[0].replace('Z', '')
                            dt = datetime.strptime(scheduled_cleaned, "%Y-%m-%d %H:%M:%S")
                        except Exception:
                            try:
                                dt = datetime.strptime(scheduled, "%Y-%m-%d %H:%M")
                            except Exception:
                                dt = datetime.fromisoformat(scheduled.replace('Z', '+00:00'))
                        scheduled_db = dt.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        scheduled_db = scheduled

                    cursor.execute("""
                        UPDATE maintenance
                        SET title = %s, description = %s, technician = %s, priority = %s, scheduled = %s, device_id = %s
                        WHERE id = %s
                    """, (
                        body.get('title', existing['title']),
                        body.get('description', existing['description']),
                        body.get('technician', existing['technician']),
                        body.get('priority', existing['priority']),
                        scheduled_db,
                        body.get('device_id', existing['device_id']),
                        event_id
                    ))
                conn.commit()
            finally:
                conn.close()
            print(f"[MAINTENANCE-UPDATED] #{event_id}", flush=True)
            self._send_json(200, {"status": "UPDATED", "id": int(event_id)})

        except Exception as e:
            print(f"[ERROR] Update maintenance failed: {e}", flush=True)
            self._send_error(400, str(e))

    def _delete_maintenance(self, event_id):
        try:
            conn = get_db()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM maintenance WHERE id = %s", (event_id,))
                    existing = cursor.fetchone()
                    if not existing:
                        self._send_error(404, f"Maintenance event #{event_id} not found")
                        return

                    cursor.execute("DELETE FROM maintenance WHERE id = %s", (event_id,))
                conn.commit()
            finally:
                conn.close()
            print(f"[MAINTENANCE-DELETED] #{event_id}", flush=True)
            self._send_json(200, {"status": "DELETED", "id": int(event_id)})
        except Exception as e:
            self._send_error(500, str(e))

    # ========== Dashboard Aggregate ==========

    def _get_dashboard(self):
        try:
            conn = get_db()
            with conn.cursor() as cursor:
                # Device counts
                cursor.execute("SELECT COUNT(*) as total FROM devices")
                total_devices = cursor.fetchone()['total']

                cursor.execute("SELECT COUNT(*) as active FROM devices WHERE status = 'RUNNING'")
                active_devices = cursor.fetchone()['active']

                cursor.execute("SELECT COUNT(*) as standby FROM devices WHERE status = 'STANDBY'")
                standby_devices = cursor.fetchone()['standby']

                # Telemetry stats
                cursor.execute("SELECT COUNT(*) as total_tel FROM telemetry")
                total_telemetry = cursor.fetchone()['total_tel']

                cursor.execute("""
                    SELECT AVG(vibration_index) as avg_vib, 
                           AVG(temperature) as avg_temp,
                           AVG(power_consumption_kw) as avg_power,
                           AVG(operating_hours) as avg_hours
                    FROM telemetry
                """)
                stats = cursor.fetchone()
                avg_vibration = round(stats['avg_vib'], 2) if stats['avg_vib'] is not None else 0.0
                avg_temperature = round(stats['avg_temp'], 1) if stats['avg_temp'] is not None else 0.0
                avg_power_consumption = round(stats['avg_power'], 2) if stats['avg_power'] is not None else 0.0
                avg_operating_hours = round(stats['avg_hours'], 2) if stats['avg_hours'] is not None else 0.0

                # Recent telemetry for chart (last 30 entries)
                cursor.execute("""
                    SELECT t.vibration_index, t.temperature, t.power_consumption_kw, t.operating_hours, t.timestamp, t.device_id, d.name as device_name
                    FROM telemetry t
                    JOIN devices d ON t.device_id = d.id
                    ORDER BY t.timestamp DESC LIMIT 30
                """)
                recent = cursor.fetchall()
                history = list(recent)
                history.reverse()

                # Upcoming maintenance
                cursor.execute("""
                    SELECT m.*, d.name as device_name
                    FROM maintenance m
                    JOIN devices d ON m.device_id = d.id
                    ORDER BY m.scheduled ASC LIMIT 5
                """)
                upcoming_maintenance = cursor.fetchall()

                # Pending maintenance count
                cursor.execute("SELECT COUNT(*) as count FROM maintenance")
                pending_maintenance = cursor.fetchone()['count']

            conn.close()

            self._send_json(200, {
                "total_devices": total_devices,
                "active_devices": active_devices,
                "standby_devices": standby_devices,
                "total_telemetry": total_telemetry,
                "avg_vibration": avg_vibration,
                "avg_temperature": avg_temperature,
                "avg_power_consumption": avg_power_consumption,
                "avg_operating_hours": avg_operating_hours,
                "pending_maintenance": pending_maintenance,
                "history": history,
                "upcoming_maintenance": upcoming_maintenance
            })
        except Exception as e:
            print(f"[ERROR] Get dashboard failed: {e}", flush=True)
            self._send_error(500, str(e))

    def log_message(self, format, *args):
        """Override to add timestamp prefix."""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}", flush=True)


# --- Main ---
if __name__ == '__main__':
    init_db()
    server = http.server.HTTPServer(('0.0.0.0', 8082), IoTInboundHandlerV3)
    print("=" * 60, flush=True)
    print("  LegacyHub API v3 (MariaDB) running on Port 8082", flush=True)
    print("=" * 60, flush=True)
    server.serve_forever()
