"""Construit le ZIP installable (extension Blender) avec l'outil officiel de Blender.

Usage : python tools/build_zip.py <chemin/vers/blender_ext.py>
   ou : blender --command extension build --source-dir mio_chain_studio --output-dir dist
"""

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "mio_chain_studio")
DIST = os.path.join(ROOT, "dist")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    tool = sys.argv[1]
    for base, dirs, files in os.walk(SRC):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(base, d))
    os.makedirs(DIST, exist_ok=True)
    subprocess.run([sys.executable, tool, "validate", SRC], check=True)
    subprocess.run([sys.executable, tool, "build", "--source-dir", SRC, "--output-dir", DIST], check=True)


if __name__ == "__main__":
    main()
