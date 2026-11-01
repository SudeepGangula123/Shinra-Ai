import glob, os, shutil, subprocess
def rd(p): return open(p, encoding="utf-8", newline=None).read()
def wr(p, s): open(p, "w", encoding="utf-8", newline="\n").write(s)
s = rd("shinri/config.py")
if "def offline" not in s:
    wr("shinri/config.py", s + '\n\ndef offline() -> bool:\n    """True only when SHINRI_OFFLINE=1 (tests set it). Skips network calls."""\n    return os.environ.get("SHINRI_OFFLINE") == "1"\n')
for p in glob.glob("shinri/*.py") + glob.glob("shinri/engines/*.py"):
    if p.endswith("config.py"): continue
    s = rd(p)
    if "PYTEST_CURRENT_TEST" not in s: continue
    s = s.replace('os.environ.get("PYTEST_CURRENT_TEST")', "offline()")
    imp = "from ..config import offline\n" if "engines" in p else "from .config import offline\n"
    if "import os\n" in s: s = s.replace("import os\n", "import os\n" + imp, 1)
    elif "from __future__ import annotations\n" in s: s = s.replace("from __future__ import annotations\n", "from __future__ import annotations\n" + imp, 1)
    else: s = imp + s
    wr(p, s)
s = rd("shinri/cards.py"); wr("shinri/cards.py", s.replace(" and offline()", ""))
s = rd("shinri/engines/claim.py"); wr("shinri/engines/claim.py", s.replace("mock = bool(offline() and len(signals) == 0)", "mock = False"))
s = rd("tests/conftest.py")
if "SHINRI_OFFLINE" not in s:
    wr("tests/conftest.py", s.replace("JPEG =", '@pytest.fixture(autouse=True)\ndef _offline(monkeypatch):\n    monkeypatch.setenv("SHINRI_OFFLINE", "1")\n\n\nJPEG =', 1))
s = rd("tests/test_api.py"); wr("tests/test_api.py", s.replace('assert runs["claim"]["mock"] and ', 'assert not runs["claim"]["mock"] and '))
s = rd("tests/test_telegram.py"); wr("tests/test_telegram.py", s.replace(' and "Demo mode" in card', ""))
subprocess.run(["git", "rm", "-q", "--cached", "-f", "shinri-ai", "scratch_test.py"])
shutil.rmtree("shinri-ai", ignore_errors=True)
if os.path.exists("scratch_test.py"): os.remove("scratch_test.py")
print("done")
