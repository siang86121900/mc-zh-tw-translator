from __future__ import annotations

import argparse
from pathlib import Path

from .translator import CTE2QuestTranslator, DEFAULT_DATA_DIR, main as interactive_main
from .verifier import verify_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mc-zh-tw-translator",
        description="Translate Minecraft mod language files, quest files, and book resources to zh_tw.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run the original interactive prompt flow.",
    )

    subparsers = parser.add_subparsers(dest="command")

    translate = subparsers.add_parser("translate", help="Translate a .jar, .zip, or folder.")
    translate.add_argument("path", help="Input .jar, .zip, or folder path.")
    translate.add_argument("-o", "--output", help="Output file or folder path.")
    translate.add_argument(
        "--engine",
        choices=["none"],
        default="none",
        help="僅使用本機／既有來源；完全不呼叫外部翻譯 API。",
    )
    translate.add_argument("--workers", type=int, default=5, help="Worker count, clamped to 1-20.")
    translate.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="Directory for ref/cache data.")

    verify = subparsers.add_parser("verify", help="Verify translated jar outputs for Forge compatibility.")
    verify.add_argument("output", help="Output .jar or folder to verify.")
    verify.add_argument("--input", help="Original input .jar or folder, used for signature and book coverage checks.")

    return parser


def run_translate(args: argparse.Namespace) -> int:
    workers = max(1, min(args.workers, 20))
    translator = CTE2QuestTranslator(
        max_workers=workers,
        engine="none",
        data_dir=args.data_dir,
    )

    input_path = Path(args.path)
    output = args.output or None

    if input_path.suffix.lower() == ".jar":
        translator.translate_jar(str(input_path), output)
    elif input_path.suffix.lower() == ".zip":
        translator.translate_zip(str(input_path), output)
    elif input_path.is_dir():
        jars = list(input_path.glob("*.jar"))
        task_files = list(input_path.glob("*.snbt")) + list(input_path.glob("*.json"))
        if jars:
            translator.translate_jar_folder(str(input_path), output)
            if task_files:
                out_dir = output or str(input_path / "translated")
                translator.translate_folder(str(input_path), out_dir)
        elif task_files:
            translator.translate_folder(str(input_path), output)
        else:
            print("找不到可處理的 .jar / .zip / .snbt / .json")
            return 1
    else:
        print(f"路徑不存在或格式不支援: {input_path}")
        return 1

    return 0


def run_verify(args: argparse.Namespace) -> int:
    result = verify_outputs(
        output_path=Path(args.output),
        input_path=Path(args.input) if args.input else None,
    )
    for warning in result.warnings:
        print(f"警告: {warning}")
    if result.ok:
        print("驗證通過")
        return 0
    print("驗證失敗")
    for error in result.errors:
        print(f"- {error}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.interactive or args.command is None:
        interactive_main()
        return 0

    if args.command == "translate":
        return run_translate(args)
    if args.command == "verify":
        return run_verify(args)

    parser.print_help()
    return 1
