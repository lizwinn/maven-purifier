# SPDX-License-Identifier: MIT
"""Checks that jdtls imports a Maven build from the lock, offline.

    python3 jdtls_check.py JDTLS BUILD_ROOT SETTINGS SOURCE_FILE

JDTLS is the jdtls launcher, BUILD_ROOT the root of a build that
`maven-purifier ide-settings` prepared, SETTINGS the ide-settings.xml it
printed, and SOURCE_FILE a Java file of the build, relative to BUILD_ROOT,
that uses a dependency. The script starts jdtls with SETTINGS as the user
settings of its embedded Maven and Maven's offline mode on, opens
SOURCE_FILE, and fails when jdtls reports an error in it, such as an import
it could not resolve. Run without network access, a clean result shows that
the editor resolved every dependency from the locked repository.
"""

import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


def main():
    jdtls, root, settings, source = sys.argv[1:5]
    root = Path(root).resolve()
    source_path = root / source
    workspace = tempfile.mkdtemp(prefix="jdtls-workspace-")
    log = Path(workspace) / "jdtls-stderr.log"
    # jdtls writes its OSGi configuration next to its data, so it runs
    # without a writable home.
    proc = subprocess.Popen(
        [jdtls, "-configuration", str(Path(workspace) / "configuration"), "-data", workspace],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log.open("w"),
    )

    def fail(message):
        print(log.read_text()[-3000:], file=sys.stderr)
        sys.exit(message)
    stdin, stdout = proc.stdin, proc.stdout
    assert stdin is not None and stdout is not None
    messages = []
    lock = threading.Condition()

    def read():
        while True:
            header = b""
            while not header.endswith(b"\r\n\r\n"):
                byte = stdout.read(1)
                if not byte:
                    return
                header += byte
            length = int(header.decode().split("Content-Length:")[1].split("\r\n")[0])
            body = json.loads(stdout.read(length))
            with lock:
                messages.append(body)
                lock.notify_all()

    threading.Thread(target=read, daemon=True).start()

    def send(message):
        data = json.dumps(message).encode()
        stdin.write(f"Content-Length: {len(data)}\r\n\r\n".encode() + data)
        stdin.flush()

    def wait_for(predicate, timeout):
        deadline = time.time() + timeout
        with lock:
            while True:
                for m in messages:
                    if predicate(m):
                        return m
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                lock.wait(remaining)

    java_settings = {
        "java": {
            "configuration": {"maven": {"userSettings": str(Path(settings).resolve())}},
            "import": {"maven": {"enabled": True, "offline": {"enabled": True}}},
        }
    }
    send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "processId": None,
                "rootUri": root.as_uri(),
                "capabilities": {"textDocument": {"publishDiagnostics": {}, "synchronization": {}}},
                "initializationOptions": {"settings": java_settings},
            },
        }
    )
    if not wait_for(lambda m: m.get("id") == 1, 120):
        fail("jdtls did not answer initialize")
    send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
    send({"jsonrpc": "2.0", "method": "workspace/didChangeConfiguration", "params": {"settings": java_settings}})

    ready = wait_for(
        lambda m: m.get("method") == "language/status" and m["params"].get("type") == "ServiceReady", 600
    )
    if not ready:
        fail("jdtls did not finish importing the build")

    def open_file(path, text):
        send(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {"textDocument": {"uri": path.as_uri(), "languageId": "java", "version": 1, "text": text}},
            }
        )

    def diagnostics(path, timeout):
        """The diagnostics jdtls last published for path, after waiting up to timeout seconds for any."""
        uri = path.as_uri()

        def published(m):
            return m.get("method") == "textDocument/publishDiagnostics" and m["params"]["uri"] == uri

        if not wait_for(published, timeout):
            return None
        # jdtls publishes again as it compiles; the last publication counts.
        time.sleep(5)
        with lock:
            return [m for m in messages if published(m)][-1]["params"]["diagnostics"]

    def errors_of(found):
        return [d for d in found if d.get("severity") == 1]

    # A control: a file beside the source that imports a class no
    # dependency has. jdtls must report it, or a clean result for the
    # source would show nothing.
    control = source_path.parent / "MavenPurifierControl.java"
    package = next(
        (line.strip().rstrip(";") for line in source_path.read_text().splitlines() if line.startswith("package ")),
        "",
    )
    # jdtls compiles only files that exist in a project's source folders,
    # so the control is written there, and removed again at the end.
    control.write_text(
        f"{package};\n\nimport org.example.doesnotexist.Missing;\n\nclass MavenPurifierControl {{ Missing m; }}\n"
    )
    try:
        open_file(control, control.read_text())
        open_file(source_path, source_path.read_text())
        control_found = diagnostics(control, 120)
        source_found = diagnostics(source_path, 120)
    finally:
        control.unlink()
    send({"jsonrpc": "2.0", "id": 2, "method": "shutdown"})
    send({"jsonrpc": "2.0", "method": "exit"})

    if control_found is None or not errors_of(control_found):
        with lock:
            for m in messages:
                if m.get("method") == "language/status" or (
                    m.get("method") == "window/logMessage" and m["params"].get("type") == 1
                ):
                    print(json.dumps(m["params"])[:300], file=sys.stderr)
        fail("jdtls reported no error for an import that cannot resolve, so its diagnostics show nothing")
    if source_found is None:
        fail(f"jdtls published no diagnostics for {source}")
    errors = errors_of(source_found)
    for d in errors:
        print(f"error: line number {d['range']['start']['line'] + 1}: {d['message']}")
    if errors:
        sys.exit(1)
    print(f"jdtls resolved {source} without errors, and reported the unresolvable import of the control")


if __name__ == "__main__":
    main()
