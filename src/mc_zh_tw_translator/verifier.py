from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


SIGNATURE_RE = re.compile(r"^META-INF/[^/]+\.(SF|RSA|DSA|EC)$", re.IGNORECASE)
BOOK_RE = re.compile(r"/(?:patchouli_books|book|books)/", re.IGNORECASE)


@dataclass
class VerifyResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.ok = False
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_jars(path: Path) -> list[Path]:
    if path.is_file() and path.suffix.lower() == ".jar":
        return [path]
    if path.is_dir():
        return sorted(path.glob("*.jar"))
    return []


def _check_python_zip(jar: Path, result: VerifyResult) -> list[str]:
    try:
        with zipfile.ZipFile(jar) as z:
            failed = z.testzip()
            if failed:
                result.fail(f"{jar.name}: ZIP CRC failed at {failed}")
            names = z.namelist()
    except Exception as e:
        result.fail(f"{jar.name}: cannot open as ZIP: {e}")
        return []

    duplicates = [name for name, count in Counter(names).items() if count > 1]
    if duplicates:
        result.fail(f"{jar.name}: duplicate ZIP entries: {duplicates[:8]}")
    return names


JAVA_RUNTIMES = ("java-runtime-epsilon", "java-runtime-delta", "java-runtime-gamma", "Jre_21", "Jre_17")


# javac --release 8 of:
#   for (String arg : Files.readAllLines(Paths.get(args[0]), UTF_8)) {
#     Path p = Paths.get(arg);
#     try (FileSystem fs = FileSystems.newFileSystem(p, (ClassLoader) null)) {}
#     catch (Throwable t) { bad++; System.out.println("BAD\t" + p.getFileName() + "\t" + Files.size(p) + "\t" + t); }
#   }
#   if (bad > 0) System.exit(1);
ZIPFS_CHECK_CLASS = (
    "yv66vgAAADQAdQoAAgADBwAEDAAFAAYBABBqYXZhL2xhbmcvT2JqZWN0AQAGPGluaXQ+AQADKClWBwAIAQAQamF2YS9sYW5nL1N0"
    "cmluZwoACgALBwAMDAANAA4BABNqYXZhL25pby9maWxlL1BhdGhzAQADZ2V0AQA7KExqYXZhL2xhbmcvU3RyaW5nO1tMamF2YS9s"
    "YW5nL1N0cmluZzspTGphdmEvbmlvL2ZpbGUvUGF0aDsJABAAEQcAEgwAEwAUAQAhamF2YS9uaW8vY2hhcnNldC9TdGFuZGFyZENo"
    "YXJzZXRzAQAFVVRGXzgBABpMamF2YS9uaW8vY2hhcnNldC9DaGFyc2V0OwoAFgAXBwAYDAAZABoBABNqYXZhL25pby9maWxlL0Zp"
    "bGVzAQAMcmVhZEFsbExpbmVzAQBAKExqYXZhL25pby9maWxlL1BhdGg7TGphdmEvbmlvL2NoYXJzZXQvQ2hhcnNldDspTGphdmEv"
    "dXRpbC9MaXN0OwsAHAAdBwAeDAAfACABAA5qYXZhL3V0aWwvTGlzdAEACGl0ZXJhdG9yAQAWKClMamF2YS91dGlsL0l0ZXJhdG9y"
    "OwsAIgAjBwAkDAAlACYBABJqYXZhL3V0aWwvSXRlcmF0b3IBAAdoYXNOZXh0AQADKClaCwAiACgMACkAKgEABG5leHQBABQoKUxq"
    "YXZhL2xhbmcvT2JqZWN0OwcALAEAFWphdmEvbGFuZy9DbGFzc0xvYWRlcgoALgAvBwAwDAAxADIBABlqYXZhL25pby9maWxlL0Zp"
    "bGVTeXN0ZW1zAQANbmV3RmlsZVN5c3RlbQEARyhMamF2YS9uaW8vZmlsZS9QYXRoO0xqYXZhL2xhbmcvQ2xhc3NMb2FkZXI7KUxq"
    "YXZhL25pby9maWxlL0ZpbGVTeXN0ZW07CgA0ADUHADYMADcABgEAGGphdmEvbmlvL2ZpbGUvRmlsZVN5c3RlbQEABWNsb3NlBwA5"
    "AQATamF2YS9sYW5nL1Rocm93YWJsZQkAOwA8BwA9DAA+AD8BABBqYXZhL2xhbmcvU3lzdGVtAQADb3V0AQAVTGphdmEvaW8vUHJp"
    "bnRTdHJlYW07BwBBAQAXamF2YS9sYW5nL1N0cmluZ0J1aWxkZXIKAEAAAwgARAEABEJBRAkKAEAARgwARwBIAQAGYXBwZW5kAQAt"
    "KExqYXZhL2xhbmcvU3RyaW5nOylMamF2YS9sYW5nL1N0cmluZ0J1aWxkZXI7CwBKAEsHAEwMAE0ATgEAEmphdmEvbmlvL2ZpbGUv"
    "UGF0aAEAC2dldEZpbGVOYW1lAQAWKClMamF2YS9uaW8vZmlsZS9QYXRoOwoAQABQDABHAFEBAC0oTGphdmEvbGFuZy9PYmplY3Q7"
    "KUxqYXZhL2xhbmcvU3RyaW5nQnVpbGRlcjsIAFMBAAEJCgAWAFUMAFYAVwEABHNpemUBABcoTGphdmEvbmlvL2ZpbGUvUGF0aDsp"
    "SgoAQABZDABHAFoBABwoSilMamF2YS9sYW5nL1N0cmluZ0J1aWxkZXI7CgBAAFwMAF0AXgEACHRvU3RyaW5nAQAUKClMamF2YS9s"
    "YW5nL1N0cmluZzsKAGAAYQcAYgwAYwBkAQATamF2YS9pby9QcmludFN0cmVhbQEAB3ByaW50bG4BABUoTGphdmEvbGFuZy9TdHJp"
    "bmc7KVYKADsAZgwAZwBoAQAEZXhpdAEABChJKVYHAGoBAApaaXBGc0NoZWNrAQAEQ29kZQEAD0xpbmVOdW1iZXJUYWJsZQEABG1h"
    "aW4BABYoW0xqYXZhL2xhbmcvU3RyaW5nOylWAQANU3RhY2tNYXBUYWJsZQEACkV4Y2VwdGlvbnMHAHIBABNqYXZhL2xhbmcvRXhj"
    "ZXB0aW9uAQAKU291cmNlRmlsZQEAD1ppcEZzQ2hlY2suamF2YQAhAGkAAgAAAAAAAgABAAUABgABAGsAAAAdAAEAAQAAAAUqtwAB"
    "sQAAAAEAbAAAAAYAAQAAAAQACQBtAG4AAgBrAAABAwAEAAYAAACUAzwqAzIDvQAHuAAJsgAPuAAVuQAbAQBNLLkAIQEAmQBtLLkA"
    "JwEAwAAHTi0DvQAHuAAJOgQZBAHAACu4AC06BRkFxgAIGQW2ADOnAD46BYQBAbIAOrsAQFm3AEISQ7YARRkEuQBJAQC2AE8SUrYA"
    "RRkEuABUtgBYElK2AEUZBbYAT7YAW7YAX6f/kBueAAcEuABlsQABADUASgBNADgAAgBsAAAAMgAMAAAABgACAAcAKwAIADUACQBA"
    "AAoASgANAE0ACgBPAAsAUgAMAIgADgCLAA8AkwAQAG8AAAAdAAb9ABgBBwAi/QAxBwAHBwBKQgcAOPkAOvoAAgcAcAAAAAQAAQBx"
    "AAEAcwAAAAIAdA=="
)


def _java_executable() -> str | None:
    """A Java 17+ runtime: the launchers' bundled ones first, since players rarely have Java on PATH."""
    import os
    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
    roots = [home / "curseforge/minecraft/Install/java/{0}/bin/java.exe"]
    roots += [p / "LocalCache/Local/runtime/{0}/windows-x64/{0}/bin/java.exe" for p in local.glob("Packages/Microsoft.4297127D64EC6_*")]
    roots += [Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Minecraft Launcher/runtime/{0}/windows-x64/{0}/bin/java.exe"]
    for name in JAVA_RUNTIMES:
        for root in roots:
            candidate = Path(str(root).format(name))
            if candidate.is_file():
                return str(candidate)
    return shutil.which("java")


def check_java_zipfs(jars: list[Path], result: VerifyResult) -> None:
    java = _java_executable()
    if not java:
        result.fail("Java not found; cannot run Forge-compatible ZipFS validation")
        return

    with tempfile.TemporaryDirectory() as tmp:
        # Launcher-bundled runtimes are JREs without a compiler, so run a precompiled class.
        (Path(tmp) / "ZipFsCheck.class").write_bytes(base64.b64decode(ZIPFS_CHECK_CLASS))
        # Java's Windows argument decoding can replace CJK filename characters.
        # Read the real paths from UTF-8 so ZipFS checks the original files.
        paths_file = Path(tmp) / "paths.txt"
        paths_file.write_text("\n".join(str(jar.resolve()) for jar in jars), encoding="utf-8")
        cmd = [java, "-Dfile.encoding=UTF-8", "-Dstdout.encoding=UTF-8", "-cp", tmp, "ZipFsCheck", str(paths_file)]
        proc = subprocess.run(cmd, text=True, encoding="utf-8", errors="replace", capture_output=True,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=120)
        if proc.returncode != 0:
            output = (proc.stdout + proc.stderr).strip()
            result.fail("Java ZipFS validation failed:\n" + output)


def check_signed_modified(input_root: Path | None, output_jars: list[Path], result: VerifyResult) -> None:
    if not input_root:
        return
    for out_jar in output_jars:
        in_jar = input_root / out_jar.name if input_root.is_dir() else input_root
        if not in_jar.exists() or sha256(in_jar) == sha256(out_jar):
            continue
        try:
            with zipfile.ZipFile(out_jar) as z:
                sigs = [n for n in z.namelist() if SIGNATURE_RE.match(n)]
        except Exception:
            continue
        if sigs:
            result.fail(f"{out_jar.name}: modified output still contains invalid signature files: {sigs}")


def _book_outputs_for(en_path: str) -> str:
    return re.sub(r"/en_us/", "/zh_tw/", en_path, flags=re.IGNORECASE)


def check_book_coverage(input_root: Path | None, output_root: Path, result: VerifyResult) -> None:
    if not input_root:
        return
    input_jars = iter_jars(input_root)
    for in_jar in input_jars:
        out_jar = output_root / in_jar.name if output_root.is_dir() else output_root
        if not out_jar.exists():
            result.fail(f"{in_jar.name}: output jar missing")
            continue
        try:
            with zipfile.ZipFile(in_jar) as zin:
                en_books = [
                    n for n in zin.namelist()
                    if BOOK_RE.search("/" + n)
                    and "/en_us/" in n.lower()
                    and n.lower().endswith((".json", ".txt"))
                ]
            if not en_books:
                continue
            with zipfile.ZipFile(out_jar) as zout:
                output_names = set(zout.namelist())
            missing = [_book_outputs_for(n) for n in en_books if _book_outputs_for(n) not in output_names]
            if missing:
                result.fail(f"{in_jar.name}: missing zh_tw book resources: {missing[:12]}")
        except Exception as e:
            result.fail(f"{in_jar.name}: book coverage check failed: {e}")


def check_lang_coverage(input_root: Path | None, output_root: Path, result: VerifyResult) -> None:
    """Ensure every en_us JSON has a corresponding zh_tw JSON in the output."""
    if not input_root:
        return
    for in_jar in iter_jars(input_root):
        out_jar = output_root / in_jar.name if output_root.is_dir() else output_root
        if not out_jar.exists():
            continue
        try:
            with zipfile.ZipFile(in_jar) as zin:
                en_files = [
                    n for n in zin.namelist()
                    if n.lower().endswith("/lang/en_us.json")
                    or n.lower().endswith("/lang/en_us.lang")
                ]
            with zipfile.ZipFile(out_jar) as zout:
                output_names = {n.lower() for n in zout.namelist()}
            missing = []
            for name in en_files:
                target = re.sub(r"en_us(\.json|\.lang)$", r"zh_tw\1", name, flags=re.IGNORECASE)
                if target.lower() not in output_names:
                    missing.append(target)
            if missing:
                result.fail(f"{in_jar.name}: missing zh_tw language resources: {missing[:12]}")
        except Exception as e:
            result.fail(f"{in_jar.name}: language coverage check failed: {e}")


def check_json_resources(output_jars: list[Path], result: VerifyResult) -> None:
    for jar in output_jars:
        try:
            with zipfile.ZipFile(jar) as z:
                for name in z.namelist():
                    lower = name.lower()
                    if not lower.endswith(".json"):
                        continue
                    if "/zh_tw/" not in lower and not lower.endswith("/zh_tw.json"):
                        continue
                    try:
                        json.loads(z.read(name).decode("utf-8-sig"))
                    except Exception as e:
                        result.fail(f"{jar.name}: invalid zh_tw JSON {name}: {e}")
        except Exception:
            pass


def verify_outputs(output_path: Path, input_path: Path | None = None) -> VerifyResult:
    result = VerifyResult()
    output_jars = iter_jars(output_path)
    if not output_jars:
        result.fail(f"No output jars found at {output_path}")
        return result

    for jar in output_jars:
        _check_python_zip(jar, result)
    check_java_zipfs(output_jars, result)
    check_signed_modified(input_path, output_jars, result)
    check_book_coverage(input_path, output_path, result)
    check_lang_coverage(input_path, output_path, result)
    check_json_resources(output_jars, result)
    return result
