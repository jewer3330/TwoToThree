"""Capture one LAN camera frame; credentials stay in the printer registry."""
import argparse
import json
import socket
import ssl
import struct
from pathlib import Path


def capture(printer, output):
    context = ssl._create_unverified_context()
    with socket.create_connection((printer['ip'], 6000), timeout=15) as raw:
        with context.wrap_socket(raw, server_hostname=printer['ip']) as connection:
            connection.settimeout(20)
            packet = struct.pack('<IIII', 0x40, 0x3000, 0, 0)
            packet += b'bblp'.ljust(32, b'\0') + printer['accessCode'].encode().ljust(32, b'\0')
            connection.sendall(packet)
            data = b''
            while len(data) < 4 * 1024 * 1024:
                block = connection.recv(65536)
                if not block: raise RuntimeError('Camera closed the connection')
                data += block
                start = data.find(b'\xff\xd8')
                end = data.find(b'\xff\xd9', max(0, start))
                if start >= 0 and end > start:
                    Path(output).write_bytes(data[start:end+2])
                    return
            raise RuntimeError('Camera did not return a JPEG')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('registry')
    parser.add_argument('output')
    args = parser.parse_args()
    printers = json.loads(Path(args.registry).read_text())
    if isinstance(printers, dict): printers = printers['printers']
    capture(printers[0], args.output)
    print(args.output)
