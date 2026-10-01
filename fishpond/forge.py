"""Forge engine plumbing for Fishpond: the pinned release, its cache, Java, the card-name index and the sim command.

Forge (https://github.com/Card-Forge/forge, GPL-3.0) is downloaded at runtime and never vendored into the repo.
Bump FORGE_VERSION deliberately: new sets arrive with new releases, and every report prints the version it ran on.
"""
import json, os, re, shutil, subprocess, sys, tarfile, zipfile

FORGE_VERSION = "2.0.15"
FORGE_URL = "https://github.com/Card-Forge/forge/releases/download/forge-{v}/forge-installer-{v}.tar.bz2"
CACHE = os.environ.get("FISHPOND_CACHE") or os.path.join(os.path.expanduser("~"), "forge-cache")
INDEX_VERSION = 1

def home(version=FORGE_VERSION): return os.path.join(CACHE, version)
def jar(version=FORGE_VERSION): return os.path.join(home(version), f"forge-gui-desktop-{version}-jar-with-dependencies.jar")
def cards_zip(version=FORGE_VERSION): return os.path.join(home(version), "res", "cardsfolder", "cardsfolder.zip")
def installed(version=FORGE_VERSION): return os.path.exists(jar(version)) and os.path.exists(cards_zip(version))

def _say(msg, quiet):
    if not quiet: print(msg, file=sys.stderr, flush=True)

def ensure(version=FORGE_VERSION, quiet=False):
    """Download and unpack the pinned release into the cache once (~300 MB download, ~470 MB unpacked). Idempotent."""
    if installed(version): return home(version)
    os.makedirs(CACHE, exist_ok=True)
    tarball = os.path.join(CACHE, f"forge-installer-{version}.tar.bz2")
    if not os.path.exists(tarball):
        url = FORGE_URL.format(v=version)
        _say(f"fishpond: downloading Forge {version} (~300 MB, about a minute) from {url}", quiet)
        part = tarball + ".part"
        if shutil.which("curl"):
            r = subprocess.run(["curl", "-sSL", "--fail", "--retry", "3", url, "-o", part])
            if r.returncode: sys.exit(f"fishpond: download failed (curl exit {r.returncode}): {url}")
        else:
            import urllib.request
            with urllib.request.urlopen(url) as resp, open(part, "wb") as fh: shutil.copyfileobj(resp, fh, 1 << 20)
        os.replace(part, tarball)
    _say(f"fishpond: unpacking Forge {version}", quiet)
    tmp = home(version) + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
    if shutil.which("tar"):
        r = subprocess.run(["tar", "-xjf", tarball, "-C", tmp])
        if r.returncode: sys.exit(f"fishpond: could not unpack {tarball} (tar exit {r.returncode}); delete it and retry")
    else:
        with tarfile.open(tarball, "r:bz2") as t: t.extractall(tmp)
    shutil.rmtree(home(version), ignore_errors=True)
    os.replace(tmp, home(version))
    os.remove(tarball)
    if not installed(version): sys.exit(f"fishpond: Forge {version} unpacked but the jar or card scripts are missing in {home(version)}")
    return home(version)

# ---------------------------------------------------------------- Java
def java_major(exe="java"):
    """Major version of `java` (or `javac`) on PATH, or 0 when it's missing."""
    if not shutil.which(exe): return 0
    r = subprocess.run([exe, "-version"], capture_output=True, text=True)
    m = re.search(r'(?:version "|javac )(\d+)', r.stderr + r.stdout)
    return int(m.group(1)) if m else 0

def install_jdk(quiet=False):
    """javac is only needed for the Java harness. On Debian/Ubuntu as root: apt-get install the JDK matching the runtime."""
    if java_major("javac"): return True
    major = java_major() or 21
    if not shutil.which("apt-get") or (hasattr(os, "geteuid") and os.geteuid() != 0):
        _say(f"fishpond: javac not found; install a JDK {major} (e.g. openjdk-{major}-jdk-headless) to use the harness", quiet)
        return False
    _say(f"fishpond: installing openjdk-{major}-jdk-headless (javac, for the harness)", quiet)
    subprocess.run(["apt-get", "update", "-q"], capture_output=True)
    r = subprocess.run(["apt-get", "install", "-y", "-q", f"openjdk-{major}-jdk-headless"], capture_output=True, text=True)
    if r.returncode: _say("fishpond: JDK install failed: " + (r.stderr or r.stdout)[-400:], quiet)
    return bool(java_major("javac"))

def memory_mb():
    """Available memory in MB (Linux /proc/meminfo; a conservative 4096 elsewhere)."""
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"): return int(line.split()[1]) // 1024
    except OSError: pass
    return 4096

# ---------------------------------------------------------------- card names
def _norm(s):
    s = s.strip().lower().replace("’", "'").replace("æ", "ae")
    return re.sub(r"\s+/{1,2}\s+", " // ", s)

def index(version=FORGE_VERSION):
    """{normalized name: [name to write in a .dck, [AI flags]]} built from Forge's card scripts once, cached as JSON.
    Full names (split cards as 'A // B') win over face names; DFC/flip/adventure/prepare cards are written by
    their front name. Flags: 'All' = AI:RemoveDeck:All (the AI can't play the card sensibly), 'Random'."""
    path = os.path.join(home(version), "fishpond_names.json")
    if os.path.exists(path):
        data = json.load(open(path, encoding="utf-8"))
        if data.get("_v") == INDEX_VERSION: return data["names"]
    full, faces = {}, {}
    with zipfile.ZipFile(cards_zip(version)) as z:
        for fn in z.namelist():
            if not fn.endswith(".txt"): continue
            txt = z.read(fn).decode("utf-8", "replace")
            parts = re.split(r"\n\s*ALTERNATE\s*\n", txt)
            names = [m.group(1).strip() for p in parts for m in [re.search(r"^Name:(.+)$", p, re.M)] if m]
            if not names: continue
            mode = (re.search(r"^AlternateMode:(\S+)", txt, re.M) or [None, ""])[1]
            deck_name = " // ".join(names) if mode == "Split" and len(names) > 1 else names[0]
            flags = sorted(set(re.findall(r"^AI:RemoveDeck:(\w+)", txt, re.M)))
            full.setdefault(_norm(deck_name), [deck_name, flags])
            for n in names: faces.setdefault(_norm(n), [deck_name, flags])
    names = dict(faces); names.update(full)
    json.dump({"_v": INDEX_VERSION, "names": names}, open(path, "w", encoding="utf-8"))
    return names

def forge_name(card, idx):
    """(name for the .dck, flags) for a Scryfall card dict, or (None, []) when Forge has no script for it."""
    tries = [card["name"]] + [f.get("name", "") for f in (card.get("card_faces") or [])[:1]]
    for t in tries:
        hit = idx.get(_norm(t))
        if hit: return hit[0], hit[1]
    return None, []

# ---------------------------------------------------------------- the stock CLI sim
def sim_cmd(deck_dir, deck_files, games, seed, clock, ai=None, xmx=1500, version=FORGE_VERSION):
    """Forge's own `sim` mode. Run it with cwd=home(): Forge finds res/ relative to the working directory.
    Decks are .dck files in deck_dir, referenced by file name (Commander needs -D for files)."""
    cmd = ["java", f"-Xmx{xmx}m", "-Djava.awt.headless=true", "-Dfile.encoding=UTF-8", "-jar", jar(version), "sim",
           "-D", os.path.join(deck_dir, ""), "-d", *deck_files, "-f", "commander", "-n", str(games), "-s", str(seed), "-c", str(clock)]
    if ai: cmd += ["-a", *ai]
    return cmd
