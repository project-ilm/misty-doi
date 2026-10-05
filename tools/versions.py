# tools/versions.py: the four places misty-doi's version is written must agree.
# © 1993–2026 Abhishek Choudhary. All rights reserved. AyeAI.
# SPDX-License-Identifier: GPL-3.0-or-later
import json
import re
import sys

v = {"pyproject.toml": re.search(r'^version = "([^"]+)"', open("pyproject.toml").read(), re.M).group(1),
     "misty/__init__.py": re.search(r'__version__ = "([^"]+)"', open("misty/__init__.py").read()).group(1),
     "misty.json": json.load(open("misty.json"))["version"],
     "CITATION.cff": re.search(r'^version: "?([^"\n]+)"?', open("CITATION.cff").read(), re.M).group(1)}
if len(set(v.values())) != 1:
    print("versions disagree:", v)
    sys.exit(1)
