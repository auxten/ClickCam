import subprocess
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import json
import sys
import time
import socket
import threading
import queue
import select
import base64
from io import BytesIO
from PIL import Image
import imagehash
import numpy as np
import chdb
from datetime import datetime
import uuid

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("server.log"), logging.StreamHandler(sys.stdout)],
)

# Global variables for image comparison
last_image_hash = None
last_response = None
HASH_THRESHOLD = 5  # Adjust this value to control sensitivity (higher = more sensitive)


class EventStore:
    def __init__(self, db_path: str = "events.db"):
        self.conn = chdb.connect(db_path)
        self.cursor = self.conn.cursor()
        self._create_database()
        self._create_table()

    def _create_database(self):
        try:
            create_database_query = """
            CREATE DATABASE IF NOT EXISTS db ENGINE = Atomic;
            """
            self.cursor.execute(create_database_query)
        except Exception as e:
            logging.warning(f"Warning when creating database: {str(e)}")

    def _create_table(self):
        try:
            create_table_query = """
            CREATE TABLE IF NOT EXISTS db.events (
                id String,
                timestamp DateTime,
                content String
            ) ENGINE = MergeTree()
            ORDER BY timestamp
            """
            self.cursor.execute(create_table_query)
        except Exception as e:
            logging.warning(f"Warning when creating table: {str(e)}")

    def add_event(self, content: str):
        try:
            event_id = str(uuid.uuid4())
            timestamp = datetime.now().strftime("'%Y-%m-%d %H:%M:%S'")
            query = f"""
            INSERT INTO db.events (id, timestamp, content)
            VALUES ('{event_id}', {timestamp}, '{content.replace("'", "''")}')
            """
            self.cursor.execute(query)
        except Exception as e:
            logging.error(f"Error adding event: {str(e)}")

    def get_recent_events(self, limit: int = 20):
        try:
            query = f"""
            SELECT timestamp, content
            FROM db.events
            ORDER BY timestamp DESC
            LIMIT {limit}
            """
            self.cursor.execute(query)
            return self.cursor.fetchall()
        except Exception as e:
            logging.error(f"Error getting recent events: {str(e)}")
            return []

    def close(self):
        self.cursor.close()
        self.conn.close()


# Initialize event store
event_store = EventStore()


def calculate_image_hash(image_data):
    """Calculate perceptual hash of an image from base64 data."""
    try:
        # Remove the data URL prefix if present
        if "," in image_data:
            image_data = image_data.split(",")[1]

        # Decode base64 and open image
        image_bytes = base64.b64decode(image_data)
        image = Image.open(BytesIO(image_bytes))

        # Calculate perceptual hash
        return imagehash.average_hash(image)
    except Exception as e:
        logging.error(f"Error calculating image hash: {str(e)}")
        return None


def images_are_similar(hash1, hash2):
    """Compare two image hashes and return True if they are similar."""
    if hash1 is None or hash2 is None:
        return False

    # Calculate Hamming distance between hashes
    distance = hash1 - hash2
    similarity = 1 - (distance / 64)  # Convert distance to similarity percentage (0-1)
    logging.info(f"Image similarity: {similarity:.2%} (distance: {distance})")
    return distance < HASH_THRESHOLD


def monitor_output(process):
    """Monitor process output using select."""
    while True:
        # Check if process is still running
        if process.poll() is not None:
            break

        # Use select to check if there's any output
        reads = [process.stdout.fileno(), process.stderr.fileno()]
        ret = select.select(reads, [], [], 0.1)

        if ret[0]:
            # Check stdout
            if process.stdout.fileno() in ret[0]:
                line = process.stdout.readline()
                if line:
                    logging.info(f"[llama-server] {line.rstrip()}")

            # Check stderr
            if process.stderr.fileno() in ret[0]:
                line = process.stderr.readline()
                if line:
                    logging.info(f"[llama-server] {line.rstrip()}")


def wait_for_port(port, host="localhost", timeout=30.0):
    """Wait for a port to be open on the specified host."""
    start_time = time.time()
    while True:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (socket.timeout, socket.error):
            if time.time() - start_time >= timeout:
                return False
            time.sleep(0.1)


class ProxyHandler(BaseHTTPRequestHandler):
    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")  # 24 hours

    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == "/events":
            try:
                events = event_store.get_recent_events()
                response_data = json.dumps(
                    [
                        {
                            "timestamp": event[0].strftime("%Y-%m-%d %H:%M:%S"),
                            "content": event[1],
                        }
                        for event in events
                    ]
                )

                self.send_response(200)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(response_data.encode())
            except Exception as e:
                logging.error(f"Error getting events: {str(e)}")
                self.send_response(500)
                self._set_cors_headers()
                self.end_headers()
        else:
            self.send_response(404)
            self._set_cors_headers()
            self.end_headers()

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)

            try:
                # Parse the request data
                request_data = json.loads(post_data.decode("utf-8"))

                # Extract image data from the request
                image_data = None
                for message in request_data.get("messages", []):
                    for content in message.get("content", []):
                        if (
                            isinstance(content, dict)
                            and content.get("type") == "image_url"
                        ):
                            image_data = content["image_url"]["url"]
                            break
                    if image_data:
                        break

                if not image_data:
                    raise ValueError("No image data found in request")

                # Calculate hash of current image
                current_hash = calculate_image_hash(image_data)

                # Compare with last image hash
                global last_image_hash, last_response
                if last_image_hash is not None and images_are_similar(
                    last_image_hash, current_hash
                ):
                    logging.info("Image too similar to previous, reusing last response")
                    if last_response:
                        self.send_response(200)
                        self._set_cors_headers()
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(last_response)
                        return
                else:
                    logging.info("Image different enough, processing with llama-server")

                # Update last image hash
                last_image_hash = current_hash

                # Forward the request to llama-server
                req = urllib.request.Request(
                    "http://localhost:8081/v1/chat/completions",
                    data=post_data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )

                with urllib.request.urlopen(req) as response:
                    response_data = response.read()
                    # Store the response for future reuse
                    last_response = response_data

                    # Parse response to get content
                    response_json = json.loads(response_data.decode("utf-8"))
                    content = response_json["choices"][0]["message"]["content"]

                    # Store event
                    event_store.add_event(content)

                    # Log the response
                    logging.info(f"Response from llama-server: {content}")

                    # Send response back to client
                    self.send_response(200)
                    self._set_cors_headers()
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(response_data)
            except Exception as e:
                logging.error(f"Error processing request: {str(e)}")
                self.send_response(500)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self._set_cors_headers()
            self.end_headers()


def start_llama_server():
    try:
        # Start llama-server with pipes for stdout and stderr
        llama_process = subprocess.Popen(
            [
                "llama-server",
                "-hf",
                "ggml-org/SmolVLM-500M-Instruct-GGUF",
                "--port",
                "8081",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            universal_newlines=True,
        )

        # Start monitoring thread
        monitor_thread = threading.Thread(target=monitor_output, args=(llama_process,))
        monitor_thread.daemon = True
        monitor_thread.start()

        logging.info("Started llama-server process, waiting for it to be ready...")

        # Wait for llama-server to be ready
        if wait_for_port(8081):
            logging.info("llama-server is ready on port 8081")
            return llama_process
        else:
            logging.error("Timeout waiting for llama-server to start")
            llama_process.terminate()
            llama_process.wait()
            sys.exit(1)
    except Exception as e:
        logging.error(f"Failed to start llama-server: {str(e)}")
        sys.exit(1)


def start_proxy_server():
    try:
        server = HTTPServer(("localhost", 8080), ProxyHandler)
        logging.info("Started proxy server on port 8080")
        server.serve_forever()
    except Exception as e:
        logging.error(f"Failed to start proxy server: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    # Start llama-server
    llama_process = start_llama_server()

    try:
        # Start proxy server
        start_proxy_server()
    except KeyboardInterrupt:
        logging.info("Shutting down servers...")
        llama_process.terminate()
        llama_process.wait()
        event_store.close()
        logging.info("Servers shut down successfully")
