from __future__ import annotations

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


def _java_executable() -> str | None:
    return shutil.which("java")


def check_java_zipfs(jars: list[Path], result: VerifyResult) -> None:
    java = _java_executable()
    if not java:
        result.fail("Java not found on PATH; cannot run Forge-compatible ZipFS validation")
        return

    source = r"""
import java.nio.file.*;
import java.nio.charset.StandardCharsets;

public class ZipFsCheck {
  public static void main(String[] args) throws Exception {
    int bad = 0;
    for (String arg : Files.readAllLines(Paths.get(args[0]), StandardCharsets.UTF_8)) {
      Path p = Paths.get(arg);
      try (FileSystem fs = FileSystems.newFileSystem(p)) {
      } catch (Throwable t) {
        bad++;
        System.out.println("BAD\t" + p.getFileName() + "\t" + Files.size(p) + "\t" + t);
      }
    }
    if (bad > 0) System.exit(1);
  }
}
"""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "ZipFsCheck.java"
        src.write_text(source, encoding="utf-8")
        # Java's Windows argument decoding can replace CJK filename characters.
        # Read the real paths from UTF-8 so ZipFS checks the original files.
        paths_file = Path(tmp) / "paths.txt"
        paths_file.write_text("\n".join(str(jar.resolve()) for jar in jars), encoding="utf-8")
        cmd = [java, "-Dfile.encoding=UTF-8", str(src), str(paths_file)]
        proc = subprocess.run(cmd, text=True, encoding="utf-8", errors="replace", capture_output=True)
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
