"""Reproduce vendored Swagger UI assets; run explicitly when updating the pin.

No npm install or runtime network dependency. Verify the entire npm tarball
against the pinned SHA-512 integrity value before reading selected files.
"""

import base64
import hashlib
import io
from pathlib import Path
import tarfile
from urllib.request import urlopen

VERSION = "5.31.0"
URL = f"https://registry.npmjs.org/swagger-ui-dist/-/swagger-ui-dist-{VERSION}.tgz"
INTEGRITY = "zSUTIck02fSga6rc0RZP3b7J7wgHXwLea8ZjgLA3Vgnb8QeOl3Wou2/j5QkzSGeoz6HusP/coYuJl33aQxQZpg=="
FILES = ("swagger-ui.css", "swagger-ui-bundle.js", "LICENSE", "NOTICE")


def main():
    with urlopen(URL, timeout=60) as response:
        archive = response.read()
    actual = base64.b64encode(hashlib.sha512(archive).digest()).decode()
    if actual != INTEGRITY:
        raise SystemExit("Swagger UI tarball integrity mismatch; no files written.")
    destination = Path(__file__).resolve().parent
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as package:
        for name in FILES:
            member = package.extractfile(f"package/{name}")
            if member is None:
                raise SystemExit(f"Missing asset: {name}")
            with member:
                (destination / name).write_bytes(member.read())
    print(f"Vendored Swagger UI {VERSION} (SHA-512 verified).")


if __name__ == "__main__":
    main()
