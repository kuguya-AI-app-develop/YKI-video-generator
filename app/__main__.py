from __future__ import annotations

import argparse
import json
import sys

from .config import ROOT, load


def main() -> int:
    parser = argparse.ArgumentParser(description="YKI-video-generator 本地短视频启动器")
    sub = parser.add_subparsers(dest="command", required=True)
    serve_parser = sub.add_parser("serve", help="启动本地创作界面")
    serve_parser.add_argument("--mode", choices=["real", "demo"])
    serve_parser.add_argument("--port", type=int)
    serve_parser.add_argument("--open", action="store_true")
    doctor_parser = sub.add_parser("doctor", help="检测运行环境，不加载模型")
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.add_argument("--mode", choices=["real", "demo"], default="real")
    download_parser = sub.add_parser("download", help="下载固定清单中的文件，支持续传与 SHA256 校验")
    download_parser.add_argument("--group", choices=["runtime", "models", "all"], default="all")
    download_parser.add_argument("--id")
    extract_parser = sub.add_parser("extract", help="校验并安全解压模型归档")
    extract_parser.add_argument("--id", required=True)
    args = parser.parse_args()
    config = load()
    if args.command == "serve":
        from .server import serve
        if args.mode:
            config["mode"] = args.mode
        if args.port:
            config["port"] = args.port
        serve(ROOT, config, open_browser=args.open)
    elif args.command == "doctor":
        from .diagnostics import doctor
        result = doctor(ROOT, config, args.mode)
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            for check in result["checks"]:
                print(f"{'OK' if check['ok'] else '!!'} {check['name']}: {check['detail']}")
        return 0 if result["ready"] else 1
    elif args.command == "download":
        from .assets import download_group
        download_group(ROOT, args.group, args.id)
    elif args.command == "extract":
        from .assets import extract
        print(extract(ROOT, args.id))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
