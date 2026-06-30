import json, time, subprocess, urllib.request, signal, sys, copy

BASE = "http://127.0.0.1:8075"

def post(path, obj):
    req = urllib.request.Request(BASE+path, data=json.dumps(obj).encode(),
        method="POST", headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())

def get(path):
    with urllib.request.urlopen(BASE+path, timeout=30) as r:
        return json.loads(r.read().decode())

proc = subprocess.Popen([sys.executable, "server.py", "--port", "8075"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    time.sleep(3)
    p = get("/api/profile")
    print("has_profile:", p["has_profile"], "| name:", p["name"], "| versions:", len(p["versions"]))
    assert p["has_profile"], "expected an existing saved profile"
    base = copy.deepcopy(p["profile"])

    # edit: tweak the name, save
    edited = copy.deepcopy(base)
    edited.setdefault("contact", {})["name"] = (edited.get("contact",{}).get("name","Test") + " (edited)")
    sv = post("/api/profile/save", {"profile": edited})
    print("after save name:", sv["name"], "| versions:", len(sv["versions"]))

    versions = sv["versions"]
    # the previous (pre-edit) version should be restorable
    older = versions[1]["id"] if len(versions) > 1 else versions[0]["id"]
    got = post("/api/profile/version", {"id": older})
    print("viewed older version name:", got["profile"].get("contact",{}).get("name"))

    rs = post("/api/profile/restore", {"id": older})
    print("restored name:", rs["name"])

    cur = get("/api/profile")
    print("current name now:", cur["name"], "| total versions:", len(cur["versions"]))

    # restore original exact base to leave things clean
    post("/api/profile/save", {"profile": base})
    print("OK")
finally:
    proc.send_signal(signal.SIGTERM); proc.wait(timeout=10)
    print("server stopped")
