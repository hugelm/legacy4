import http.server
import json
import pymysql
import pymysql.cursors
import os
import re
import sys
import time
from datetime import datetime, timedelta

DB_HOST = os.environ.get('DB_HOST', 'db')
DB_USER = os.environ.get('DB_USER', 'legacy_user')
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'legacy_pass')
DB_NAME = os.environ.get('DB_NAME', 'legacyhub')

MIN_SCHEDULED_YEAR = 2020
MAX_SCHEDULED_YEAR = 2035

IP_PATTERN = re.compile(
    r'^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}'
    r'(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$'
)


class ApiError(Exception):
    """Expected API failure with an HTTP status code and client-safe message."""

    def __init__(self, message, status_code=400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def validate_ip_address(ip):
    ip = (ip or '').strip()
    if not ip:
        raise ApiError("IP address is required")
    if not IP_PATTERN.match(ip):
        raise ApiError(f"Invalid IP address: '{ip}'")
    return ip


def parse_and_validate_scheduled(scheduled):
    if isinstance(scheduled, datetime):
        dt = scheduled
    elif isinstance(scheduled, str):
        scheduled = scheduled.strip()
        if not scheduled:
            raise ApiError("Scheduled date is required")

        dt = None
        cleaned = scheduled.replace('T', ' ').split('.')[0].replace('Z', '')
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                dt = datetime.strptime(cleaned, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            try:
                dt = datetime.fromisoformat(scheduled.replace('Z', '+00:00'))
                if dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
            except ValueError as exc:
                raise ApiError(
                    "Invalid date format. Use YYYY-MM-DD HH:MM or a valid ISO datetime."
                ) from exc
    else:
        raise ApiError("Scheduled date must be a string or datetime")

    if dt.year < MIN_SCHEDULED_YEAR or dt.year > MAX_SCHEDULED_YEAR:
        raise ApiError(
            f"Year must be between {MIN_SCHEDULED_YEAR} and {MAX_SCHEDULED_YEAR} (got {dt.year})."
        )

    return dt.strftime("%Y-%m-%d %H:%M:%S")


def require_text(value, field_name):
    text = (value or '').strip()
    if not text:
        raise ApiError(f"Field '{field_name}' is required")
    return text


def get_db():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )


def init_db():
    print("[DB] Initializing database...", flush=True)
    retries = 30
    conn = None
    while retries > 0:
        try:
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

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS technicians (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    name        VARCHAR(255) NOT NULL UNIQUE,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            cursor.execute("SELECT COUNT(*) as count FROM technicians")
            if cursor.fetchone()['count'] == 0:
                default_technicians = [
                    ('Markus Rühl',),
                    ('Claudia Obert',),
                    ('Leon Gooretzzkaaa',),
                    ('Luke Skywalker',),
                ]
                cursor.executemany(
                    "INSERT INTO technicians (name) VALUES (%s)",
                    default_technicians
                )

            for index_sql in (
                "CREATE INDEX idx_telemetry_device ON telemetry(device_id)",
                "CREATE INDEX idx_telemetry_timestamp ON telemetry(timestamp DESC)",
                "CREATE INDEX idx_maintenance_device ON maintenance(device_id)",
                "CREATE INDEX idx_maintenance_scheduled ON maintenance(scheduled)",
            ):
                try:
                    cursor.execute(index_sql)
                except Exception:
                    pass

            cursor.execute("SELECT COUNT(*) as count FROM devices")
            device_count = cursor.fetchone()['count']

            if device_count == 0:
                print("[DB] Database is empty. Seeding sample datasets...", flush=True)

                default_devices = [
                    ('192.168.10.101', 'Pump Alpha-01', 'Custom IoT Device', 'API Ingestion', 'RUNNING', 'fa-fan'),
                    ('192.168.10.102', 'Turbine Beta-02', 'OPC-UA Embedded Link', 'Edge Gateway', 'STANDBY', 'fa-bolt'),
                    ('192.168.10.103', 'Compressor Gamma-03', 'Modbus RTU Bridge', 'Direct Backend Node', 'OFFLINE', 'fa-server')
                ]
                cursor.executemany("""
                    INSERT INTO devices (id, name, type, ingress, status, icon)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, default_devices)

                base_time = datetime.now()
                telemetry_data = []
                for i in range(15):
                    ts = (base_time - timedelta(minutes=(15 - i) * 5)).strftime("%Y-%m-%d %H:%M:%S")

                    telemetry_data.append((
                        '192.168.10.101',
                        float(round(4.0 + (i % 3) * 0.4 + (i % 2) * 0.2, 2)),
                        float(round(60.0 + i * 0.8, 1)),
                        float(round(11.5 + (i % 4) * 0.5, 2)),
                        float(round(230.5 + i * 0.08, 2)),
                        'RUNNING',
                        ts
                    ))
                    telemetry_data.append((
                        '192.168.10.102',
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

                maint_events = [
                    ('192.168.10.101', 'Scheduled Calibration', 'Routine sensor re-calibration.', 'Markus Rühl', 'routine', (base_time + timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")),
                    ('192.168.10.102', 'Filter Replacement', 'Replace air intake and cooling filters.', 'Claudia Obert', 'medium', (base_time + timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")),
                    ('192.168.10.103', 'Emergency Bearing Check', 'Address high vibration warnings.', 'Leon Gooretzzkaaa', 'immediate', (base_time + timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S")),
                    ('192.168.10.101', 'Annual Safety Inspection', 'Full safety audit and firmware check.', 'Luke Skywalker', 'low', (base_time + timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")),
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


class IoTInboundHandler(http.server.BaseHTTPRequestHandler):

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
        self._send_json(status_code, {
            "success": False,
            "status": "ERROR",
            "error": error_message,
            "code": status_code
        })

    def _run(self, action, handler):
        """Run a handler with unified error mapping."""
        try:
            handler()
        except ApiError as err:
            self._send_error(err.status_code, err.message)
        except pymysql.Error as err:
            print(f"[ERROR] {action}: {err}", flush=True)
            self._send_error(500, "Database operation failed")
        except Exception as err:
            print(f"[ERROR] {action}: {err}", flush=True)
            self._send_error(500, "Internal server error")

    def _read_body(self):
        content_length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(content_length)
        if not raw:
            return {}
        try:
            return json.loads(raw.decode('utf-8'))
        except json.JSONDecodeError as err:
            raise ApiError("Invalid JSON in request body") from err

    def _parse_path(self):
        return [s for s in self.path.split('?')[0].split('/') if s]

    def _parse_query(self):
        query_string = self.path.split('?')[1] if '?' in self.path else ''
        return dict(p.split('=') for p in query_string.split('&') if '=' in p)

    def _require_device(self, cursor, device_id):
        cursor.execute("SELECT * FROM devices WHERE id = %s", (device_id,))
        device = cursor.fetchone()
        if not device:
            raise ApiError(f"Device '{device_id}' not found", 404)
        return device

    def _require_maintenance(self, cursor, event_id):
        cursor.execute("SELECT * FROM maintenance WHERE id = %s", (event_id,))
        event = cursor.fetchone()
        if not event:
            raise ApiError(f"Maintenance event #{event_id} not found", 404)
        return event

    def _require_technician(self, cursor, technician_id):
        cursor.execute("SELECT * FROM technicians WHERE id = %s", (technician_id,))
        technician = cursor.fetchone()
        if not technician:
            raise ApiError(f"Technician #{technician_id} not found", 404)
        return technician

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        segments = self._parse_path()

        if segments == ['api', 'devices']:
            self._run("get devices", self._get_devices)
        elif segments == ['api', 'telemetry']:
            self._run("get telemetry", self._get_telemetry)
        elif segments == ['api', 'maintenance']:
            self._run("get maintenance", self._get_maintenance)
        elif segments == ['api', 'technicians']:
            self._run("get technicians", self._get_technicians)
        elif segments == ['api', 'dashboard']:
            self._run("get dashboard", self._get_dashboard)
        elif segments == ['api', 'db-info']:
            self._run("get db-info", self._get_db_info)
        elif segments == ['api', 'db-info', 'reveal']:
            self._run("get db-info reveal", self._reveal_db_password)
        else:
            self._send_error(404, "Endpoint not found")

    def do_POST(self):
        segments = self._parse_path()

        if segments == ['api', 'devices']:
            self._run("create device", self._create_device)
        elif segments == ['api', 'telemetry']:
            self._run("create telemetry", self._create_telemetry)
        elif segments == ['api', 'maintenance']:
            self._run("create maintenance", self._create_maintenance)
        elif segments == ['api', 'technicians']:
            self._run("create technician", self._create_technician)
        else:
            self._send_error(404, "Endpoint not found")

    def do_PUT(self):
        segments = self._parse_path()

        if len(segments) == 3 and segments[:2] == ['api', 'devices']:
            self._run("update device", lambda: self._update_device(segments[2]))
        elif len(segments) == 3 and segments[:2] == ['api', 'maintenance']:
            self._run("update maintenance", lambda: self._update_maintenance(segments[2]))
        elif len(segments) == 3 and segments[:2] == ['api', 'technicians']:
            self._run("update technician", lambda: self._update_technician(segments[2]))
        else:
            self._send_error(404, "Endpoint not found")

    def do_DELETE(self):
        segments = self._parse_path()

        if len(segments) == 3 and segments[:2] == ['api', 'devices']:
            self._run("delete device", lambda: self._delete_device(segments[2]))
        elif len(segments) == 3 and segments[:2] == ['api', 'maintenance']:
            self._run("delete maintenance", lambda: self._delete_maintenance(segments[2]))
        elif len(segments) == 3 and segments[:2] == ['api', 'technicians']:
            self._run("delete technician", lambda: self._delete_technician(segments[2]))
        else:
            self._send_error(404, "Endpoint not found")

    def _get_devices(self):
        conn = get_db()
        try:
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
        finally:
            conn.close()
        self._send_json(200, rows)

    def _create_device(self):
        body = self._read_body()
        ip_address = validate_ip_address(body.get('ip_address', body.get('id', '')))
        name = require_text(body.get('name'), 'name')

        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM devices WHERE id = %s", (ip_address,))
                if cursor.fetchone():
                    raise ApiError(f"Device with IP '{ip_address}' already exists", 409)

                cursor.execute("""
                    INSERT INTO devices (id, name, type, ingress, status, icon)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    ip_address,
                    name,
                    body.get('type', 'Custom IoT Device'),
                    body.get('ingress', 'API Ingestion'),
                    body.get('status', 'STANDBY'),
                    body.get('icon', 'fa-microchip')
                ))
            conn.commit()
        finally:
            conn.close()

        print(f"[DEVICE-CREATED] {ip_address} ({name})", flush=True)
        self._send_json(201, {"status": "CREATED", "device_id": ip_address, "ip_address": ip_address})

    def _update_device(self, device_id):
        validate_ip_address(device_id)
        body = self._read_body()

        conn = get_db()
        try:
            with conn.cursor() as cursor:
                existing = self._require_device(cursor, device_id)
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
        finally:
            conn.close()

        print(f"[DEVICE-UPDATED] {device_id}", flush=True)
        self._send_json(200, {"status": "UPDATED", "device_id": device_id})

    def _delete_device(self, device_id):
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                self._require_device(cursor, device_id)
                cursor.execute("DELETE FROM devices WHERE id = %s", (device_id,))
            conn.commit()
        finally:
            conn.close()

        print(f"[DEVICE-DELETED] {device_id} (cascade: telemetry + maintenance)", flush=True)
        self._send_json(200, {"status": "DELETED", "device_id": device_id})

    def _get_telemetry(self):
        params = self._parse_query()
        device_id = params.get('device_id')
        if device_id:
            device_id = validate_ip_address(device_id)

        try:
            limit = int(params.get('limit', 50))
        except ValueError as err:
            raise ApiError("Query parameter 'limit' must be an integer") from err
        if limit < 1 or limit > 500:
            raise ApiError("Query parameter 'limit' must be between 1 and 500")

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

    def _create_telemetry(self):
        body = self._read_body()
        device_id = validate_ip_address(body.get('device_id', ''))

        try:
            vibration = float(body.get('vibration_index', 0.0))
            temperature = float(body.get('temperature', 0.0))
            power_consumption_kw = float(body.get('power_consumption_kw', 0.0))
            operating_hours = float(body.get('operating_hours', 0.0))
        except (TypeError, ValueError) as err:
            raise ApiError("Telemetry numeric fields must be valid numbers") from err

        status = body.get('status', 'RUNNING')
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = get_db()
        try:
            with conn.cursor() as cursor:
                self._require_device(cursor, device_id)
                cursor.execute("""
                    INSERT INTO telemetry (device_id, vibration_index, temperature, power_consumption_kw, operating_hours, status, timestamp)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (device_id, vibration, temperature, power_consumption_kw, operating_hours, status, timestamp))
                cursor.execute("UPDATE devices SET status = %s WHERE id = %s", (status, device_id))
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

    def _get_maintenance(self):
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

    def _create_maintenance(self):
        body = self._read_body()
        device_id = validate_ip_address(body.get('device_id', ''))
        title = require_text(body.get('title'), 'title')
        scheduled_db = parse_and_validate_scheduled(body.get('scheduled', ''))
        technician = (body.get('technician') or '').strip()

        conn = get_db()
        try:
            with conn.cursor() as cursor:
                self._require_device(cursor, device_id)
                cursor.execute("""
                    INSERT INTO maintenance (device_id, title, description, technician, priority, scheduled)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    device_id,
                    title,
                    body.get('description', ''),
                    technician,
                    body.get('priority', 'routine'),
                    scheduled_db
                ))
                new_id = cursor.lastrowid
            conn.commit()
        finally:
            conn.close()

        print(f"[MAINTENANCE-CREATED] #{new_id} for {device_id}: {title}", flush=True)
        self._send_json(201, {"status": "CREATED", "id": new_id})

    def _update_maintenance(self, event_id):
        body = self._read_body()

        conn = get_db()
        try:
            with conn.cursor() as cursor:
                existing = self._require_maintenance(cursor, event_id)
                device_id = validate_ip_address(body.get('device_id', existing['device_id']))
                scheduled_db = parse_and_validate_scheduled(body.get('scheduled', existing['scheduled']))
                technician = (body.get('technician', existing['technician']) or '').strip()

                cursor.execute("""
                    UPDATE maintenance
                    SET title = %s, description = %s, technician = %s, priority = %s, scheduled = %s, device_id = %s
                    WHERE id = %s
                """, (
                    body.get('title', existing['title']),
                    body.get('description', existing['description']),
                    technician,
                    body.get('priority', existing['priority']),
                    scheduled_db,
                    device_id,
                    event_id
                ))
            conn.commit()
        finally:
            conn.close()

        print(f"[MAINTENANCE-UPDATED] #{event_id}", flush=True)
        self._send_json(200, {"status": "UPDATED", "id": int(event_id)})

    def _delete_maintenance(self, event_id):
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                self._require_maintenance(cursor, event_id)
                cursor.execute("DELETE FROM maintenance WHERE id = %s", (event_id,))
            conn.commit()
        finally:
            conn.close()

        print(f"[MAINTENANCE-DELETED] #{event_id}", flush=True)
        self._send_json(200, {"status": "DELETED", "id": int(event_id)})

    def _get_technicians(self):
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM technicians ORDER BY name ASC")
                rows = cursor.fetchall()
        finally:
            conn.close()
        self._send_json(200, rows)

    def _create_technician(self):
        body = self._read_body()
        name = require_text(body.get('name'), 'name')

        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM technicians WHERE name = %s", (name,))
                if cursor.fetchone():
                    raise ApiError(f"Technician '{name}' already exists", 409)

                cursor.execute("INSERT INTO technicians (name) VALUES (%s)", (name,))
                new_id = cursor.lastrowid
            conn.commit()
        finally:
            conn.close()

        print(f"[TECHNICIAN-CREATED] #{new_id} {name}", flush=True)
        self._send_json(201, {"status": "CREATED", "id": new_id, "name": name})

    def _update_technician(self, technician_id):
        body = self._read_body()
        name = require_text(body.get('name'), 'name')

        conn = get_db()
        try:
            with conn.cursor() as cursor:
                existing = self._require_technician(cursor, technician_id)
                cursor.execute(
                    "SELECT * FROM technicians WHERE name = %s AND id != %s",
                    (name, technician_id)
                )
                if cursor.fetchone():
                    raise ApiError(f"Technician '{name}' already exists", 409)

                old_name = existing['name']
                cursor.execute("UPDATE technicians SET name = %s WHERE id = %s", (name, technician_id))
                if old_name != name:
                    cursor.execute(
                        "UPDATE maintenance SET technician = %s WHERE technician = %s",
                        (name, old_name)
                    )
            conn.commit()
        finally:
            conn.close()

        print(f"[TECHNICIAN-UPDATED] #{technician_id} -> {name}", flush=True)
        self._send_json(200, {"status": "UPDATED", "id": int(technician_id), "name": name})

    def _delete_technician(self, technician_id):
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                existing = self._require_technician(cursor, technician_id)
                cursor.execute("DELETE FROM technicians WHERE id = %s", (technician_id,))
            conn.commit()
        finally:
            conn.close()

        print(f"[TECHNICIAN-DELETED] #{technician_id} ({existing['name']})", flush=True)
        self._send_json(200, {"status": "DELETED", "id": int(technician_id)})

    def _get_dashboard(self):
        conn = get_db()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) as total FROM devices")
                total_devices = cursor.fetchone()['total']

                cursor.execute("SELECT COUNT(*) as active FROM devices WHERE status = 'RUNNING'")
                active_devices = cursor.fetchone()['active']

                cursor.execute("SELECT COUNT(*) as standby FROM devices WHERE status = 'STANDBY'")
                standby_devices = cursor.fetchone()['standby']

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

                cursor.execute("""
                    SELECT t.vibration_index, t.temperature, t.power_consumption_kw, t.operating_hours, t.timestamp, t.device_id, d.name as device_name
                    FROM telemetry t
                    JOIN devices d ON t.device_id = d.id
                    ORDER BY t.timestamp DESC LIMIT 30
                """)
                recent = cursor.fetchall()
                history = list(recent)
                history.reverse()

                cursor.execute("""
                    SELECT m.*, d.name as device_name
                    FROM maintenance m
                    JOIN devices d ON m.device_id = d.id
                    ORDER BY m.scheduled ASC LIMIT 5
                """)
                upcoming_maintenance = cursor.fetchall()

                cursor.execute("SELECT COUNT(*) as count FROM maintenance")
                pending_maintenance = cursor.fetchone()['count']
        finally:
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

    def _get_db_info(self):
        self._send_json(200, {
            "host": DB_HOST,
            "database": DB_NAME,
            "user": DB_USER
        })

    def _reveal_db_password(self):
        self._send_json(200, {
            "password": DB_PASSWORD
        })

    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}", flush=True)


if __name__ == '__main__':
    init_db()
    server = http.server.HTTPServer(('0.0.0.0', 8080), IoTInboundHandler)
    print("=" * 60, flush=True)
    print("  LegacyHub API running on Port 8080", flush=True)
    print("=" * 60, flush=True)
    server.serve_forever()
