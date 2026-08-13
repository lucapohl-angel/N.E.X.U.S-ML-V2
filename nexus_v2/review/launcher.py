"""Launch the private reviewer in a separate terminal and localhost browser."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import webbrowser
from functools import partial
from pathlib import Path
from threading import Thread

from nexus_v2.review.builder import build_review_state
from nexus_v2.review.dataset import GameCapture, discover_games, load_review_state
from nexus_v2.review.export import export_review_truth
from nexus_v2.review.server import ReviewSession, create_server


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_dataset() -> Path:
    return project_root() / "data/private/review_dataset"


def _select_capture(dataset: Path, *, family_id: str | None, game_id: str | None) -> GameCapture:
    games = discover_games(dataset)
    if family_id is not None:
        games = tuple(game for game in games if game.family_id == family_id)
    if game_id is not None:
        games = tuple(game for game in games if game.game_id == game_id)
    complete = tuple(game for game in games if game.complete_capture)
    if not complete:
        incomplete = "\n".join(
            f"  {game.family_id}/{game.game_id}: missing {', '.join(game.missing_files())}"
            for game in games
        )
        raise ValueError("no complete review capture is ready\n" + incomplete)
    if len(complete) == 1:
        return complete[0]
    print("\nComplete games:\n")
    for index, game in enumerate(complete, start=1):
        state = load_review_state(game)
        if state is None:
            status = "not started"
        elif state.complete:
            status = "complete"
        else:
            counts = state.counts()
            final = counts["accepted"] + counts["edited"] + counts["unknown"]
            status = f"{final}/{len(state.records)} final"
        print(f"  {index}. {game.family_id}/{game.game_id} — {status}")
    while True:
        answer = input("\nChoose game number: ").strip()
        try:
            selected = int(answer) - 1
        except ValueError:
            print("Enter one of the listed numbers.")
            continue
        if 0 <= selected < len(complete):
            return complete[selected]
        print("Enter one of the listed numbers.")


def _terminal_command(arguments: list[str]) -> list[str]:
    root = project_root()
    review_command = [
        "uv",
        "run",
        "--with",
        "rapidocr-onnxruntime",
        "nexus-review",
        "--serve",
        *arguments,
    ]
    shell_command = f"cd {shlex.quote(str(root))} && {shlex.join(review_command)}"
    if shutil.which("konsole"):
        return ["konsole", "--noclose", "-e", "bash", "-lc", shell_command]
    if shutil.which("gnome-terminal"):
        return ["gnome-terminal", "--", "bash", "-lc", shell_command + "; exec bash"]
    if shutil.which("kitty"):
        return ["kitty", "bash", "-lc", shell_command + "; exec bash"]
    if shutil.which("alacritty"):
        return ["alacritty", "-e", "bash", "-lc", shell_command + "; exec bash"]
    if shutil.which("xterm"):
        return ["xterm", "-hold", "-e", "bash", "-lc", shell_command]
    raise RuntimeError("no supported terminal emulator was found")


def _launch_separate_terminal(args: argparse.Namespace) -> int:
    forwarded = ["--dataset", str(args.dataset), "--port", str(args.port)]
    if args.family:
        forwarded.extend(("--family", args.family))
    if args.game:
        forwarded.extend(("--game", args.game))
    if args.hero_prototypes:
        forwarded.extend(("--hero-prototypes", str(args.hero_prototypes)))
    forwarded.extend(("--hero-recognition-mode", args.hero_recognition_mode))
    if args.item_prototypes:
        forwarded.extend(("--item-prototypes", str(args.item_prototypes)))
    if args.visual_only:
        forwarded.append("--visual-only")
    if args.item_exceptions_only:
        forwarded.append("--item-exceptions-only")
    if args.no_open:
        forwarded.append("--no-open")
    process = subprocess.Popen(_terminal_command(forwarded), start_new_session=True)
    print(f"Opened N.E.X.U.S review terminal (PID {process.pid}).")
    return 0


def _serve(args: argparse.Namespace) -> int:
    root = project_root()
    tessdata = root / ".work/tessdata/eng.traineddata"
    if tessdata.is_file():
        os.environ.setdefault("TESSDATA_PREFIX", str(tessdata.parent))
    capture = _select_capture(args.dataset, family_id=args.family, game_id=args.game)
    if args.item_exceptions_only and not args.visual_only:
        raise ValueError("--item-exceptions-only requires --visual-only")
    if args.visual_only != capture.visual_batch_capture:
        expected = "--visual-only" if capture.visual_batch_capture else "full-match mode"
        raise ValueError(f"selected capture requires {expected}")
    print(f"\nSelected: {capture.family_id}/{capture.game_id}")
    print(f"Sources:  {capture.path}")
    state = load_review_state(capture)
    if state is None:
        print("\nNo draft exists. Running the local engine; this can take about one minute.\n")
        state = build_review_state(
            capture,
            project_root=root,
            hero_prototypes=args.hero_prototypes,
            hero_recognition_mode=args.hero_recognition_mode,
            item_prototypes=args.item_prototypes,
            use_rapidocr=not args.visual_only,
            visual_only=args.visual_only,
            item_exceptions_only=args.item_exceptions_only,
            progress=lambda message: print(f"  {message}", flush=True),
        )
    else:
        expected_scope = (
            "hero_plus_item_exceptions"
            if args.item_exceptions_only
            else "hero_item_only"
            if args.visual_only
            else "full_match"
        )
        if state.engine.get("review_scope", "full_match") != expected_scope:
            raise ValueError(
                f"saved review scope does not match requested mode: expected {expected_scope}"
            )
        saved_recognition_mode = state.engine.get("hero_recognition_mode", "original")
        if saved_recognition_mode != args.hero_recognition_mode:
            raise ValueError(
                "saved hero recognition mode does not match requested mode: "
                f"expected {args.hero_recognition_mode}, got {saved_recognition_mode}"
            )
        print(f"Loaded saved review progress: {capture.state_path}")
    catalog_path = root / "catalogs/staging/user-approved-2026-08-01-r2/catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    correction_options = {
        "hero": tuple(
            (str(entity["id"]), str(entity["canonical_name"])) for entity in catalog["heroes"]
        ),
        "item": tuple(
            (str(entity["id"]), str(entity["canonical_name"]))
            for entity in catalog["items"]
            if entity.get("classification_enabled", False)
        ),
    }
    exporter = partial(export_review_truth, catalog_path=catalog_path)
    if state.complete:
        export_review_truth(capture, state, catalog_path=catalog_path)
        print("Exported reviewed TXT truth files.")
    session = ReviewSession(
        capture,
        state,
        correction_options=correction_options,
        truth_exporter=exporter,
    )
    server = create_server(session, port=args.port)
    actual_port = int(server.server_address[1])
    url = f"http://127.0.0.1:{actual_port}/"
    print(f"\nReviewer: {url}")
    print("The server is localhost-only. Press Ctrl+C in this terminal to stop it.\n")
    if not args.no_open:
        Thread(
            target=webbrowser.open,
            args=(url,),
            kwargs={"new": 1, "autoraise": True},
            daemon=True,
            name="nexus-review-browser-opener",
        ).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping reviewer…")
    finally:
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review N.E.X.U.S screenshot truth locally")
    parser.add_argument("--dataset", type=Path, default=default_dataset())
    parser.add_argument("--family")
    parser.add_argument("--game")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--hero-prototypes", type=Path)
    parser.add_argument(
        "--hero-recognition-mode",
        choices=("original", "strict", "balanced"),
        default="balanced",
        help="hero operating point; balanced is the default and strict/original are fallbacks",
    )
    parser.add_argument("--item-prototypes", type=Path)
    parser.add_argument(
        "--visual-only",
        action="store_true",
        help="review independent hero-item screenshots without OCR fields",
    )
    parser.add_argument(
        "--item-exceptions-only",
        action="store_true",
        help="review every hero plus only abstained, seven-slot, or semantically warned items",
    )
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-open", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.dataset = args.dataset.expanduser().resolve()
    if args.hero_prototypes is not None:
        args.hero_prototypes = args.hero_prototypes.expanduser().resolve()
    if args.item_prototypes is not None:
        args.item_prototypes = args.item_prototypes.expanduser().resolve()
    try:
        return _serve(args) if args.serve else _launch_separate_terminal(args)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"nexus-review: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
