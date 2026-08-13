import json
import socket
import sys
import uuid

script_path = sys.argv[1]
request = {
    "id": str(uuid.uuid4()),
    "command": "python.execute",
    "params": {"script_path": script_path, "timeout_seconds": 300},
}
with socket.create_connection(("127.0.0.1", 9876), timeout=310) as sock:
    sock.sendall((json.dumps(request) + "\n").encode())
    data = b""
    while b"\n" not in data:
        data += sock.recv(65536)
print(json.dumps(json.loads(data.split(b"\n", 1)[0]), indent=2))
