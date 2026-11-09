# SPDX-License-Identifier: GPL-3.0-or-later
"""The ``vocalkeep`` command.

The desktop app calls these commands, so their names and flags are a contract: add to them,
don't change them. Exit codes: 0 success, 1 a problem explained on stderr, 2 bad usage.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from vocalkeep import __version__
from vocalkeep.errors import VocalkeepError
from vocalkeep.progress import Reporter

ISSUES_URL = "https://github.com/lobojoel2003/Vocalkeep/issues"

Handler = Callable[[argparse.Namespace], int]


def _print_json(data: Any) -> None:
    sys.stdout.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _reporter(args: argparse.Namespace, *, to_stderr: bool = False) -> Reporter:
    mode = getattr(args, "progress", "text") or "text"
    stream = sys.stderr if (to_stderr and mode == "text") else None
    return Reporter(mode, stream)  # type: ignore[arg-type]


# --- doctor ---------------------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    from vocalkeep.doctor import format_report, report

    result = report(args.python, check_torch=not args.no_torch)
    if args.json:
        _print_json(result)
    else:
        print(format_report(result))
    return 0


# --- bases ----------------------------------------------------------------------------------


def cmd_bases(args: argparse.Namespace) -> int:
    from vocalkeep.bases import commercial_text, list_bases

    bases = list_bases(args.language, commercial_only=args.commercial)
    if args.json:
        _print_json([b.to_dict() for b in bases])
        return 0
    if not bases:
        print("No base voices match. Try without --language or --commercial.")
        return 0
    print("Base voices to start from (* = recommended):\n")
    for b in bases:
        mark = "*" if b.recommended else " "
        print(f"{mark} {b.id}  -  {b.name}")
        print(f"    Licence: {b.license}. {commercial_text(b.commercial)}")
        extra = "" if b.can_fine_tune else f" {b.speakers} speakers (can't be used yet)."
        print(f"    {b.lineage}.{extra}")
        print(f"    {b.notes}")
        print()
    print("Use one with:  vocalkeep build BANK --base ljspeech -o VOICES_DIR")
    return 0


# --- check ----------------------------------------------------------------------------------


def cmd_check(args: argparse.Namespace) -> int:
    from vocalkeep.bank import open_bank
    from vocalkeep.dataset import check_bank

    with open_bank(args.bank) as bank:
        result = check_bank(bank)
    if args.json:
        _print_json(result)
        return 0
    c = result["counts"]
    name = result["bank"]["speaker"].get("name") or "this voice bank"
    print(f"Voice bank: {name} ({c['takes']} recordings)")
    print(
        f"Good: {c['good']}   Okay: {c['okay']}   Worth redoing: {c['redo']}   "
        f"Missing: {c['missing']}   Unreadable: {c['unreadable']}"
    )
    print(f"Speech: {result['speechMinutes']:.1f} minutes")
    if c["noText"]:
        print(f"{c['noText']} recording(s) have no sentence text, so training can't use them.")
    if result["redo"]:
        print("\nWorth recording again:")
        for e in result["redo"]:
            text = e["text"] if len(e["text"]) <= 60 else e["text"][:57] + "..."
            print(f'  {e["promptId"]}  "{text}"  - {e["message"]}')
    else:
        print("\nNothing needs recording again.")
    print(f"\n{c['usable']} recordings can be used for training.")
    return 0


# --- prepare --------------------------------------------------------------------------------


def cmd_prepare(args: argparse.Namespace) -> int:
    from vocalkeep.bank import open_bank
    from vocalkeep.dataset import prepare

    reporter = _reporter(args)
    reporter.stage("prepare")
    with open_bank(args.bank) as bank:
        info = prepare(
            bank,
            args.output,
            min_verdict=args.min_verdict,
            sample_rate=args.sample_rate,
            espeak_voice=args.espeak_voice,
            reporter=reporter,
        )
    out = str(Path(args.output).expanduser().resolve())
    c = info["counts"]
    reporter.done(
        f"Prepared {c['included']} recordings ({info['minutes']:.1f} minutes) in {out}"
        + (f"; {c['excluded']} left out (see dataset.json)." if c["excluded"] else "."),
        dataset=out,
        included=c["included"],
        excluded=c["excluded"],
        minutes=info["minutes"],
    )
    return 0


# --- train ----------------------------------------------------------------------------------


def _plan_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "epochs": args.epochs,
        "quick": args.quick,
        "batch_size": args.batch_size,
        "accelerator": args.accelerator,
        "devices": args.devices,
        "checkpoint": args.checkpoint,
        "python": args.python,
        "require_commercial": args.require_commercial,
    }


def _report_dry_run(reporter: Reporter, plan: Any, extra: dict[str, Any] | None = None) -> None:
    from vocalkeep.bases import licence_notice

    if reporter.is_json:
        for line in licence_notice(plan.base).splitlines():
            reporter.log(line)
        reporter.done(
            "Dry run: nothing was downloaded or trained.",
            dryRun=True,
            command=plan.command,
            maxEpochs=plan.max_epochs,
            baseEpoch=plan.base_epoch,
            extraEpochs=plan.extra_epochs,
            checkpoint=str(plan.checkpoint),
            download=plan.checkpoint_url if plan.needs_download else None,
            **(extra or {}),
        )
        return
    print(licence_notice(plan.base))
    print()
    if plan.needs_download:
        print(f"Would download {plan.checkpoint_url}\n  to {plan.checkpoint}")
    else:
        print(f"Starting checkpoint: {plan.checkpoint}")
    print(
        f"Epochs: the checkpoint is at epoch {plan.base_epoch} ({plan.epoch_source}); "
        f"{plan.extra_epochs} more means --trainer.max_epochs {plan.max_epochs}."
    )
    labels = {
        "usableRecordings": "Recordings that can be used",
        "recordingsToRedo": "Recordings worth redoing",
        "work": "Work folder",
        "voice": "The voice will be made in",
    }
    for key, value in (extra or {}).items():
        print(f"{labels.get(key, key)}: {value}")
    print("\nTraining command:")
    print(plan.command_text)


def cmd_train(args: argparse.Namespace) -> int:
    from vocalkeep.train import plan_training, run_training

    reporter = _reporter(args)
    plan = plan_training(args.dataset, args.base, args.output, **_plan_kwargs(args))
    if args.dry_run:
        _report_dry_run(reporter, plan)
        return 0
    run = run_training(plan, reporter=reporter)
    out = str(plan.run_dir)
    reporter.done(
        f"Training finished. Make the voice with:  vocalkeep export {out} -o VOICES_DIR",
        run=out,
        checkpoint=run.get("checkpoint"),
    )
    return 0


# --- export ---------------------------------------------------------------------------------


def cmd_export(args: argparse.Namespace) -> int:
    from vocalkeep.export import export_voice

    reporter = _reporter(args)
    voice = export_voice(
        args.run,
        args.output,
        name=args.name,
        checkpoint=args.checkpoint,
        python=args.python,
        reporter=reporter,
    )
    reporter.done(f"Your voice is ready: {voice.root}", voice=str(voice.root), id=voice.id)
    return 0


# --- build ----------------------------------------------------------------------------------


def cmd_build(args: argparse.Namespace) -> int:
    from vocalkeep.bank import open_bank, safe_name
    from vocalkeep.dataset import check_bank, prepare
    from vocalkeep.doctor import python_path, training_ready, training_steps
    from vocalkeep.export import export_voice
    from vocalkeep.languages import espeak_voice_for, normalize_tag
    from vocalkeep.paths import cache_dir
    from vocalkeep.train import plan_training, run_training
    from vocalkeep.voice import make_voice_id

    reporter = _reporter(args)
    voices_dir = Path(args.output).expanduser().resolve()
    with open_bank(args.bank) as bank:
        work = (
            Path(args.work).expanduser().resolve()
            if args.work
            else cache_dir() / "work" / safe_name(bank.id or bank.speaker.name or "bank")
        )
        dataset_dir = work / "dataset"
        run_dir = work / "run"
        name = args.name or bank.speaker.name or "vocalkeep"
        voice_id = make_voice_id(bank.speaker.language, name)

        if args.dry_run:
            report = check_bank(bank)
            language = normalize_tag(bank.speaker.language)
            info = {
                "format": "vocalkeep-dataset",
                "bank": {"id": bank.id},
                "speaker": bank.speaker.to_dict(),
                "language": language,
                "espeakVoice": espeak_voice_for(language),
                "sampleRate": args.sample_rate,
                "counts": {"included": report["counts"]["usable"]},
            }
            plan = plan_training(
                dataset_dir, args.base, run_dir, dataset_info=info, **_plan_kwargs(args)
            )
            _report_dry_run(
                reporter,
                plan,
                {
                    "usableRecordings": report["counts"]["usable"],
                    "recordingsToRedo": report["counts"]["redo"],
                    "work": str(work),
                    "voice": str(voices_dir / voice_id),
                },
            )
            return 0

        python = python_path(args.python)
        ready, info_probe = training_ready(python)
        if not ready:
            raise VocalkeepError(
                "This computer isn't set up to train voices yet.",
                training_steps(python, info_probe) + "\nThen run 'vocalkeep doctor' to check.",
            )
        reporter.stage("prepare", "Getting your recordings ready")
        prepare(
            bank,
            dataset_dir,
            min_verdict=args.min_verdict,
            sample_rate=args.sample_rate,
            reporter=reporter,
        )
    plan = plan_training(dataset_dir, args.base, run_dir, **_plan_kwargs(args))
    run_training(plan, reporter=reporter, check_environment=False)
    voice = export_voice(run_dir, voices_dir, name=args.name, python=python, reporter=reporter)
    reporter.done(
        f"Your voice is ready: {voice.root}",
        voice=str(voice.root),
        id=voice.id,
    )
    return 0


# --- speak ----------------------------------------------------------------------------------


def cmd_speak(args: argparse.Namespace) -> int:
    from vocalkeep.speak import speak
    from vocalkeep.voice import load_voice

    voice = load_voice(args.voice)
    text = args.text if args.text not in (None, "-") else sys.stdin.read()
    out = Path(args.output).expanduser() if args.output else None
    result = speak(voice, text, out, args.length_scale)
    if result is not None:
        print(f"Saved {result.resolve()}")
    return 0


# --- package --------------------------------------------------------------------------------


def cmd_package(args: argparse.Namespace) -> int:
    from vocalkeep.package import package_voice
    from vocalkeep.voice import load_voice

    voice = load_voice(args.voice)
    reporter = _reporter(args, to_stderr=True)
    formats = [f.strip() for f in args.format.split(",") if f.strip()]
    made = package_voice(
        voice, formats, args.output, espeak_data=args.espeak_data, reporter=reporter
    )
    paths = [str(p.resolve()) for p in made]
    if args.json:
        _print_json(paths)
    else:
        for p in paths:
            print(p)
    return 0


# --- install / uninstall --------------------------------------------------------------------


def cmd_install(args: argparse.Namespace) -> int:
    from vocalkeep.install import instructions
    from vocalkeep.voice import load_voice

    reporter = _reporter(args)
    if args.target in ("saywell", "android", "nvda", "macos"):
        voice = None
        try:
            voice = load_voice(args.voice)
        except VocalkeepError:
            voice = None
        for line in instructions(args.target, voice, args.voice):
            print(line)
        return 0

    voice = load_voice(args.voice)
    if args.target == "linux":
        from vocalkeep.install.linux import MODULE_NAME, install_linux

        result = install_linux(
            voice, make_default=args.make_default, dry_run=args.dry_run, reporter=reporter
        )
        summary = (
            "Dry run: nothing was changed."
            if args.dry_run
            else f'Installed. Test it with: spd-say -o {MODULE_NAME} "Hello"'
        )
    else:
        from vocalkeep.install.windows import install_windows

        wresult = install_windows(
            voice, dry_run=args.dry_run, espeak_data=args.espeak_data, reporter=reporter
        )
        result = wresult  # type: ignore[assignment]
        summary = (
            "Dry run: nothing was changed."
            if args.dry_run
            else "Copied. Now open VoiceGarden and click 'Install to SAPI' for the voice."
        )
    label = "Would" if args.dry_run else "Done"
    print(f"{label}:")
    for action in result.actions:
        print(f"  - {action}")
    if result.next_steps:
        print("Next:")
        for step in result.next_steps:
            print(f"  - {step}")
    print(summary)
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    reporter = _reporter(args)
    if args.target == "linux":
        from vocalkeep.install.linux import uninstall_linux

        result: Any = uninstall_linux(args.voice_id, reporter=reporter)
    else:
        from vocalkeep.install.windows import uninstall_windows

        result = uninstall_windows(args.voice_id, reporter=reporter)
    for action in result.actions:
        print(f"  - {action}")
    for step in result.next_steps:
        print(f"Next: {step}")
    print(f"Removed {args.voice_id}.")
    return 0


# --- parser ---------------------------------------------------------------------------------


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} isn't a whole number") from None
    if n <= 0:
        raise argparse.ArgumentTypeError("must be at least 1")
    return n


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="show technical details (tracebacks) when something goes wrong",
    )
    progress = argparse.ArgumentParser(add_help=False)
    progress.add_argument(
        "--progress",
        choices=("text", "json"),
        default="text",
        help="how to report progress: friendly text, or JSON lines for the desktop app",
    )

    parser = argparse.ArgumentParser(
        prog="vocalkeep",
        description=(
            "Turn a Vocalkeep voice bank into your own Piper voice, and install it as a system "
            "voice. Typical use: vocalkeep build BANK --base ljspeech -o VOICES"
        ),
        epilog="Run 'vocalkeep COMMAND --help' for the details of a command.",
    )
    parser.add_argument("--version", action="version", version=f"vocalkeep {__version__}")
    parser.add_argument("--debug", action="store_true", default=False, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    def add(name: str, handler: Handler, help_text: str, parents: Sequence[Any] = ()) -> Any:
        p = sub.add_parser(name, help=help_text, description=help_text, parents=[common, *parents])
        p.set_defaults(handler=handler)
        return p

    p = add("doctor", cmd_doctor, "Check what this computer can do and what to install next.")
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    p.add_argument("--python", help="check another Python (for example a training environment)")
    p.add_argument("--no-torch", action="store_true", help="skip the (slow) PyTorch/GPU check")

    p = add("bases", cmd_bases, "List the base voices a new voice can start from, with licences.")
    p.add_argument("--json", action="store_true", help="print the list as JSON")
    p.add_argument(
        "--commercial", action="store_true", help="only voices cleared for commercial use"
    )
    p.add_argument("--language", help="only this language, e.g. en-US or en")

    p = add("check", cmd_check, "Check every recording in a voice bank again.")
    p.add_argument("bank", metavar="BANK", help="voice bank folder or backup .zip")
    p.add_argument("--json", action="store_true", help="print the report as JSON")

    def dataset_options(p: Any) -> None:
        p.add_argument(
            "--min-verdict",
            choices=("okay", "good"),
            default=None,
            help="lowest quality to include (default: okay)",
        )
        p.add_argument(
            "--sample-rate",
            type=_positive_int,
            default=22050,
            help="sample rate of the training audio (default: 22050, what Piper expects)",
        )

    p = add("prepare", cmd_prepare, "Prepare a voice bank as a training dataset.", [progress])
    p.add_argument("bank", metavar="BANK", help="voice bank folder or backup .zip")
    p.add_argument("-o", "--output", required=True, metavar="DATASET", help="dataset folder")
    dataset_options(p)
    p.add_argument("--espeak-voice", help="espeak-ng voice to read the text with (e.g. en-us)")

    def train_options(p: Any) -> None:
        p.add_argument("--base", required=True, metavar="ID", help="base voice (see 'bases')")
        p.add_argument(
            "--epochs",
            type=_positive_int,
            metavar="EXTRA",
            help="epochs to train on top of the base voice (default 1000; 150 with --quick)",
        )
        p.add_argument("--quick", action="store_true", help="a short preview run (150 epochs)")
        p.add_argument("--batch-size", type=_positive_int, default=16, help="default: 16")
        p.add_argument("--accelerator", default="auto", help="auto, gpu or cpu (default: auto)")
        p.add_argument("--devices", default="1", help="how many GPUs to use (default: 1)")
        p.add_argument(
            "--checkpoint",
            metavar="PATH_OR_URL",
            help="use this base checkpoint instead of downloading the base voice's",
        )
        p.add_argument("--dry-run", action="store_true", help="show what would run, then stop")
        p.add_argument(
            "--require-commercial",
            action="store_true",
            help="refuse base voices whose licence doesn't allow commercial use",
        )
        p.add_argument("--python", help="Python with Piper's training tools (default: this one)")

    p = add("train", cmd_train, "Fine-tune a voice on a prepared dataset.", [progress])
    p.add_argument("dataset", metavar="DATASET", help="folder made by 'vocalkeep prepare'")
    p.add_argument("-o", "--output", required=True, metavar="RUN", help="training run folder")
    train_options(p)

    p = add("export", cmd_export, "Make the finished voice from a training run.", [progress])
    p.add_argument("run", metavar="RUN", help="folder made by 'vocalkeep train'")
    p.add_argument("-o", "--output", required=True, metavar="VOICES_DIR", help="where voices go")
    p.add_argument("--name", help="the voice's name (default: the speaker's name)")
    p.add_argument("--checkpoint", metavar="PATH", help="export this checkpoint")
    p.add_argument("--python", help="Python with Piper's training tools (default: this one)")

    p = add("build", cmd_build, "Prepare, train and export a voice in one go.", [progress])
    p.add_argument("bank", metavar="BANK", help="voice bank folder or backup .zip")
    p.add_argument("-o", "--output", required=True, metavar="VOICES_DIR", help="where voices go")
    p.add_argument("--work", metavar="DIR", help="folder for the dataset and training run")
    p.add_argument("--name", help="the voice's name (default: the speaker's name)")
    train_options(p)
    dataset_options(p)

    p = add("speak", cmd_speak, "Say something with a voice.")
    p.add_argument("voice", metavar="VOICE", help="voice folder or .onnx file")
    p.add_argument("text", nargs="?", help="what to say (default: read from standard input)")
    p.add_argument("-o", "--output", metavar="OUT.wav", help="save to a WAV file instead")
    p.add_argument(
        "--length-scale", type=float, default=1.0, help="speed: above 1 is slower (default 1.0)"
    )

    p = add("package", cmd_package, "Make voice packages for apps and devices.", [progress])
    p.add_argument("voice", metavar="VOICE", help="voice folder or .onnx file")
    p.add_argument(
        "--format",
        required=True,
        metavar="FORMAT",
        help="piper, nvda, sherpa, saywell, sherpatts, voicegarden or all "
        "(several: comma-separated)",
    )
    p.add_argument("-o", "--output", required=True, metavar="OUT_DIR", help="where packages go")
    p.add_argument("--espeak-data", metavar="DIR", help="espeak-ng-data folder to include")
    p.add_argument("--json", action="store_true", help="print the files made as a JSON list")

    from vocalkeep.install import INSTALL_TARGETS

    p = add("install", cmd_install, "Install a voice as a system voice.")
    p.add_argument("voice", metavar="VOICE", help="voice folder or .onnx file")
    p.add_argument("--target", required=True, choices=INSTALL_TARGETS, help="where to install")
    p.add_argument(
        "--make-default", action="store_true", help="make it the voice everything uses (linux)"
    )
    p.add_argument("--dry-run", action="store_true", help="show what would change, then stop")
    p.add_argument("--espeak-data", metavar="DIR", help="espeak-ng-data folder (windows)")

    p = add("uninstall", cmd_uninstall, "Remove a voice installed with 'vocalkeep install'.")
    p.add_argument("voice_id", metavar="VOICE_ID", help="the voice's id, e.g. en_US-jane-medium")
    p.add_argument("--target", required=True, choices=("linux", "windows"))
    return parser


def _setup_streams() -> None:
    """Text always goes out as UTF-8 when another program reads it (the desktop app does), and
    an odd console encoding never crashes the tool."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            if os.name == "nt" and not stream.isatty():
                reconfigure(encoding="utf-8", errors="replace")
            else:
                reconfigure(errors="replace")
        except (ValueError, OSError):  # pragma: no cover - stream already in use or closed
            pass


def main(argv: Sequence[str] | None = None) -> int:
    _setup_streams()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:  # --help, --version and usage errors
        return int(e.code) if isinstance(e.code, int) else (0 if e.code is None else 2)
    if not getattr(args, "handler", None):
        parser.print_help()
        return 2
    debug = bool(getattr(args, "debug", False))
    progress_mode = getattr(args, "progress", "text")
    try:
        code: int = args.handler(args)
        return code
    except VocalkeepError as e:
        if progress_mode == "json":
            Reporter("json").error(e.message, e.hint)
        print(f"Error: {e.message}", file=sys.stderr)
        if e.hint:
            print(e.hint, file=sys.stderr)
        if debug:
            traceback.print_exc()
        return 1
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        return 1
    except BrokenPipeError:
        # The reader went away (e.g. "| head"). Stop quietly.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 1
    except Exception as e:
        if progress_mode == "json":
            Reporter("json").error(f"Something unexpected went wrong: {e}")
        print(f"Error: something unexpected went wrong: {type(e).__name__}: {e}", file=sys.stderr)
        if debug:
            traceback.print_exc()
        else:
            print(
                f"Run the same command with --debug for details, and please report it at "
                f"{ISSUES_URL}",
                file=sys.stderr,
            )
        return 1


if __name__ == "__main__":
    sys.exit(main())
