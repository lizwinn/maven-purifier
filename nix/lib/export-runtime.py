# SPDX-License-Identifier: MIT
"""Export Maven's evaluated project runtime artifacts, excluding its tool realms."""
import json
from pathlib import Path
import sys

sys.path.insert(0, sys.argv[1])
import coursier_runtime

records, repository, catalog, destination = map(Path, sys.argv[2:])
paths = set()
for line in records.read_text().splitlines():
    event = json.loads(line)
    if event.get('event') == 'runtime':
        paths.add(event['file'])
coursier_runtime.export(repository, sorted(paths), catalog, destination)
