"""Forge engine plumbing for Fishpond: the pinned release, its cache, Java, the card-name index and the sim command.

Forge (https://github.com/Card-Forge/forge, GPL-3.0) is downloaded at runtime and never vendored into the repo.
Bump FORGE_VERSION deliberately: new sets arrive with new releases, and every report prints the version it ran on.
"""
import glob, json, os, re, shutil, subprocess, sys, tarfile, zipfile

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
    r = subprocess.run(["tar", "-xjf", tarball, "-C", tmp]) if shutil.which("tar") else None
    if r is None or r.returncode:  # no tar, or a Windows tar that can't read bz2: Python's tarfile can
        shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
        with tarfile.open(tarball, "r:bz2") as t: t.extractall(tmp)
    shutil.rmtree(home(version), ignore_errors=True)
    os.replace(tmp, home(version))
    os.remove(tarball)
    if not installed(version): sys.exit(f"fishpond: Forge {version} unpacked but the jar or card scripts are missing in {home(version)}")
    return home(version)

# ---------------------------------------------------------------- Java
# ---------------------------------------------------------------- Forge patches
PATCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forge_patches")
FORGE_SRC_URL = "https://raw.githubusercontent.com/Card-Forge/forge/forge-{v}/{path}"

def pilot_on():
    """The pilot improvements (tutor policy, '-pilot-' AI patches, card overrides) are always on; FISHPOND_PILOT=off turns them
    all off so an A/B run can measure them against stock Forge AI. Crash-fix patches stay on either way."""
    return os.environ.get("FISHPOND_PILOT", "on").lower() != "off"

def patch_files():
    """The repo's fixes to Forge (fishpond/forge_patches/*.patch, unified diffs against the pinned release's source).
    '-pilot-' patches improve the AI's play (docs/FORGE_PLAN.md, "Pilot policy"); the rest fix crashes."""
    fs = sorted(glob.glob(os.path.join(PATCH_DIR, "*.patch")))
    return fs if pilot_on() else [f for f in fs if "-pilot-" not in os.path.basename(f)]

def patched_classes(version=FORGE_VERSION, quiet=False):
    """Build the patched Forge classes once per (version, patches): fetch each patched file from the release tag on GitHub,
    apply the patches, compile against the release jar. The class dir goes ahead of the jar on the classpath, so only these
    classes change. Forge stays downloaded at run time, never vendored; a patch that no longer applies after a version bump
    stops here with the file named (docs/FORGE_ISSUES.md, "Patches")."""
    import hashlib, urllib.request
    pf = patch_files()
    if not pf: return None
    h = hashlib.sha1((version + "".join(open(f, encoding="utf-8").read() for f in pf)).encode()).hexdigest()[:12]
    d = os.path.join(home(version), "fishpond-patched", h)
    if os.path.exists(os.path.join(d, "ok")): return d
    paths = []
    for f in pf:
        for line in open(f, encoding="utf-8"):
            if line.startswith("+++ b/"): paths.append(line[6:].strip())
    tmp = f"{d}.tmp{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    src = os.path.join(tmp, "src"); out = os.path.join(tmp, "classes")
    _say(f"fishpond: building {len(pf)} Forge patch(es) for {version}", quiet)
    for p in sorted(set(paths)):
        dst = os.path.join(src, *p.split("/")); os.makedirs(os.path.dirname(dst), exist_ok=True)
        url = FORGE_SRC_URL.format(v=version, path=p)
        try:
            with urllib.request.urlopen(url) as resp, open(dst, "wb") as fh: fh.write(resp.read())
        except Exception as e: sys.exit(f"fishpond: could not fetch Forge source {url}: {e}")
    for f in pf:
        r = subprocess.run(["git", "apply", "--whitespace=nowarn", f], cwd=src, capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"fishpond: Forge patch {os.path.basename(f)} does not apply to Forge {version}:\n{(r.stderr or r.stdout).strip()}\n"
                     "Re-check it against the new release (docs/FORGE_ISSUES.md, Patches): fixed upstream -> delete it; moved -> regenerate it.")
    os.makedirs(out, exist_ok=True)
    javas = [os.path.join(src, *p.split("/")) for p in sorted(set(paths))]
    r = subprocess.run(["javac", "-nowarn", "-encoding", "UTF-8", "-cp", jar(version), "-d", out, *javas], capture_output=True, text=True)
    if r.returncode: sys.exit("fishpond: compiling the Forge patches failed:\n" + (r.stderr + r.stdout)[-2000:])
    open(os.path.join(out, "ok"), "w").write("\n".join(os.path.basename(f) for f in pf))
    shutil.rmtree(d, ignore_errors=True)
    try: os.replace(out, d)
    except OSError: pass                                   # another run got there first
    shutil.rmtree(tmp, ignore_errors=True)
    return d

OVERRIDE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forge_card_overrides")

def override_files():
    """Fishpond's replacement card scripts (fishpond/forge_card_overrides/*.txt, each a full Forge card script)."""
    return sorted(glob.glob(os.path.join(OVERRIDE_DIR, "*.txt"))) if pilot_on() else []

def card_script(name, version=FORGE_VERSION):
    """A card's script text from the pinned release (exact Name: match), or None."""
    with zipfile.ZipFile(cards_zip(version)) as z:
        for fn in z.namelist():
            if not fn.endswith(".txt"): continue
            txt = z.read(fn).decode("utf-8", "replace")
            m = re.search(r"^Name:(.+)$", txt, re.M)
            if m and m.group(1).strip() == name: return txt
    return None

def write_unflag_override(name, why, version=FORGE_VERSION):
    """Write fishpond/forge_card_overrides/<name>.txt: the release's script without AI:RemoveDeck:All. Forge's AI never casts or
    activates a card with that hint (AiController drops its abilities), so this is how a card the AI turns out to play
    acceptably (checked by a puzzle) becomes playable. Returns the path."""
    txt = card_script(name, version)
    if txt is None: sys.exit(f"fishpond: Forge {version} has no card named {name!r}")
    body = "\n".join(l for l in txt.splitlines() if not l.startswith("AI:RemoveDeck:All")) + "\n"
    os.makedirs(OVERRIDE_DIR, exist_ok=True)
    p = os.path.join(OVERRIDE_DIR, re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") + ".txt")
    header = f"# fishpond override (Forge {version} script minus AI:RemoveDeck:All): {why}\n"
    open(p, "w", encoding="utf-8").write(header + body)
    return p

def _link(src, dst):
    """Mirror src at dst without copying. Symlinks elsewhere; on Windows a symlink needs admin or Developer Mode, so
    directories become junctions and files hard links (neither needs a privilege; the cache is on one volume)."""
    if os.name != "nt": return os.symlink(src, dst)
    if os.path.isdir(src):
        import _winapi
        return _winapi.CreateJunction(src, dst)
    os.link(src, dst)

def run_home(version=FORGE_VERSION, quiet=False):
    """The directory Forge runs from (its cwd: it reads res/ relative to it). Without card overrides that's the install;
    with them, a mirror of the install whose res/cardsfolder/cardsfolder.zip has the overridden scripts swapped in
    (Forge reads only the zip when it exists). Built once per (version, overrides); everything else is linked (_link)."""
    import hashlib
    files = override_files()
    if not files: return home(version)
    h = hashlib.sha1((version + "".join(open(f, encoding="utf-8").read() for f in files)).encode()).hexdigest()[:12]
    d = os.path.join(home(version), "fishpond-cards", h)
    if os.path.exists(os.path.join(d, "ok")): return d
    tmp = f"{d}.tmp{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True); os.makedirs(os.path.join(tmp, "res", "cardsfolder"))
    src = home(version)
    for e in os.listdir(src):
        if e not in ("res", "fishpond-cards", "fishpond-harness", "fishpond-patched"): _link(os.path.join(src, e), os.path.join(tmp, e))
    for e in os.listdir(os.path.join(src, "res")):
        if e != "cardsfolder": _link(os.path.join(src, "res", e), os.path.join(tmp, "res", e))
    repl = {}
    for f in files:
        txt = open(f, encoding="utf-8").read()
        m = re.search(r"^Name:(.+)$", txt, re.M)
        if not m: sys.exit(f"fishpond: card override {f} has no Name: line")
        repl[m.group(1).strip()] = txt
    found = set()
    with zipfile.ZipFile(cards_zip(version)) as zin, zipfile.ZipFile(os.path.join(tmp, "res", "cardsfolder", "cardsfolder.zip"), "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename.endswith(".txt"):
                m = re.search(rb"^Name:(.+)$", data, re.M)
                name = m.group(1).decode("utf-8", "replace").strip() if m else None
                if name in repl:
                    data = repl[name].encode("utf-8"); found.add(name)
            zout.writestr(info, data)
    missing = set(repl) - found
    if missing: sys.exit(f"fishpond: card overrides name cards Forge {version} doesn't have: {sorted(missing)}")
    _say(f"fishpond: card overrides applied ({len(repl)}): {', '.join(sorted(repl))}", quiet)
    open(os.path.join(tmp, "ok"), "w").write("\n".join(sorted(repl)))
    shutil.rmtree(d, ignore_errors=True)
    try: os.replace(tmp, d)
    except OSError: shutil.rmtree(tmp, ignore_errors=True)
    return d

def latest_release(timeout=10):
    """The newest Forge release tag on GitHub ("2.0.16"), or None offline. Releases come every 6-8 weeks."""
    import urllib.request
    try:
        req = urllib.request.Request("https://api.github.com/repos/Card-Forge/forge/releases/latest", headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r: tag = json.load(r).get("tag_name", "")
        return tag[len("forge-"):] if tag.startswith("forge-") else None
    except Exception: return None

def _vkey(v): return tuple(int(x) for x in re.findall(r"\d+", v))

def _java_ok(exe):
    """True for a Java 17+ that is not the 32-bit Client VM (which can't reserve Forge's multi-GB heap)."""
    try: r = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError): return False
    out = r.stderr + r.stdout
    m = re.search(r'version "(\d+)', out)
    return bool(m) and int(m.group(1)) >= 17 and "Client VM" not in out

def prefer_modern_java():
    r"""An old 32-bit java first on PATH (Windows keeps one in Common Files\Oracle\Java\java8path) fails Forge with
    'Could not reserve enough space for object heap'. If PATH's java isn't usable, put a JDK/JRE 17+ bin first on PATH."""
    exe = "java.exe" if os.name == "nt" else "java"
    if shutil.which("java") and _java_ok("java"): return
    import glob
    roots = [os.environ.get("JAVA_HOME", "")]
    for base in (os.environ.get("LOCALAPPDATA", "") + "/Programs/Eclipse Adoptium", "C:/Program Files/Eclipse Adoptium",
                 "C:/Program Files/Java", "C:/Program Files/Microsoft", "C:/Program Files/Zulu", "C:/Program Files/Amazon Corretto",
                 "/usr/lib/jvm"):
        roots += sorted(glob.glob(base + "/*"), reverse=True)
    for root in roots:
        bindir = os.path.join(root, "bin")
        if root and os.path.exists(os.path.join(bindir, exe)) and _java_ok(os.path.join(bindir, exe)):
            os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")
            return

prefer_modern_java()

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
    """Available memory in MB (Linux /proc/meminfo, Windows GlobalMemoryStatusEx; a conservative 4096 elsewhere)."""
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"): return int(line.split()[1]) // 1024
    except OSError: pass
    if os.name == "nt":
        import ctypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        st = MEMORYSTATUSEX(); st.dwLength = ctypes.sizeof(st)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)): return int(st.ullAvailPhys // (1024 * 1024))
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
