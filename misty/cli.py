"""misty — command-line entry point.

Design contract (the thing that makes Misty automation-friendly):

  * Credentials come ONLY from the environment (ZENODO_TOKEN, optionally
    ORCID and ZENODO_SANDBOX). No prompt, ever. A missing token is a clean
    exit-3, not a hang.
  * Every command is non-interactive. Input is a metadata file + artifact
    paths; output is files on disk plus a result JSON on stdout.
  * Exit codes are stable and map to error classes (see misty.errors):
        0 ok | 1 generic | 2 metadata | 3 config/creds | 4 zenodo | 5 ots
  * Human status goes to stderr; machine output goes to stdout. So
        DOI=$(misty publish -m meta.json -f a.zip | jq -r .doi)
    works in a pipeline with no scraping.

So any upstream workflow only has to: (1) emit canonical metadata, (2) export
ZENODO_TOKEN, (3) call `misty publish`. Nothing else.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from . import __version__, metadata, ots, package, result, transform
from .errors import MistyError

EXIT_OK = 0


def _log(msg: str) -> None:
    print(f"[misty] {msg}", file=sys.stderr, flush=True)


def _emit(obj: Dict[str, Any], output: Optional[str]) -> None:
    """Write machine output to stdout and, if requested, to a file."""
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        _log(f"wrote {output}")
    print(text)


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_init(args) -> int:
    if os.path.exists(args.output) and not args.force:
        _log(f"{args.output} exists (use --force to overwrite)")
        return 1
    template = {
        "title": "",
        "version": "1.0.0",
        "upload_type": "software",
        "description": "",
        "license": "gpl-3.0",
        "access_right": "open",
        "creators": [{"name": "Family, Given", "affiliation": "", "orcid": ""}],
        "keywords": [],
        "related_identifiers": [],
        "repository": "",
    }
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(template, fh, indent=2, ensure_ascii=False)
    _log(f"wrote metadata template -> {args.output}")
    return EXIT_OK


def cmd_validate(args) -> int:
    m = metadata.load(args.metadata)
    errs = metadata.validate(m)
    if errs:
        for e in errs:
            _log(f"INVALID: {e}")
        return 2
    _log("metadata OK")
    return EXIT_OK


def cmd_transform(args) -> int:
    m = metadata.load_validate_normalize(args.metadata)
    os.makedirs(args.outdir, exist_ok=True)
    written = package.build_metadata_files(m, args.outdir)
    for p in written:
        _log(f"wrote {p}")
    return EXIT_OK


def cmd_package(args) -> int:
    m = metadata.load_validate_normalize(args.metadata)
    manifest = package.build_package(m, args.files, args.outdir, doi=args.doi)
    _log(f"package ready in {args.outdir}")
    _emit(manifest, args.output)
    return EXIT_OK


def cmd_ots(args) -> int:
    if args.action == "stamp":
        out = ots.stamp(args.path)
        _log(f"stamped -> {out}")
    elif args.action == "verify":
        _log(ots.verify(args.path).strip())
    elif args.action == "upgrade":
        _log(ots.upgrade(args.path).strip())
    return EXIT_OK


def cmd_publish(args) -> int:
    """The one-shot automation command: metadata + files -> DOI."""
    m = metadata.load_validate_normalize(args.metadata)

    # Inject ORCID from env into creators lacking one (automation convenience).
    env_orcid = os.environ.get("ORCID")
    if env_orcid:
        for c in m["creators"]:
            c.setdefault("orcid", env_orcid)

    files: List[str] = list(args.files)
    file_records = [
        __import__("misty.checksum", fromlist=["file_record"]).file_record(f)
        for f in files
    ]
    for r in file_records:
        _log(f"sha256 {r['name']}: {r['sha256']}")

    # Always build the offline package alongside (unless suppressed).
    if not args.no_package:
        package.build_package(m, files, args.package_dir, doi=m.get("doi"))
        _log(f"package -> {args.package_dir}")

    if args.dry_run:
        _log("dry-run: skipping all network calls")
        res = result.build(
            deposition_id=None, bucket=None, sandbox=bool(args.sandbox),
            files=file_records, state="dry-run",
        )
        _emit(res, args.output)
        return EXIT_OK

    # Network phase — token strictly from env unless --token given.
    from .zenodo import ZenodoClient
    client = ZenodoClient(token=args.token, sandbox=args.sandbox)
    _log(f"target: {'SANDBOX' if client.sandbox else 'PRODUCTION'} ({client.base})")

    dep_id, bucket, _dep = client.create_deposition()
    _log(f"deposition {dep_id} bucket {bucket}")

    for f in files:
        info = client.upload_file(bucket, f)
        _log(f"uploaded {info.get('key', os.path.basename(f))} "
             f"({info.get('size', '?')} bytes)")

    client.set_metadata(dep_id, transform.to_zenodo(m))
    _log("metadata set")

    if args.no_publish:
        _log("draft created; not publishing (--no-publish)")
        res = result.build(
            deposition_id=dep_id, bucket=bucket, sandbox=client.sandbox,
            files=file_records, state="draft",
        )
        _emit(res, args.output)
        return EXIT_OK

    record = client.publish(dep_id)
    res = result.from_zenodo_record(record, sandbox=client.sandbox, files=file_records)
    _log(f"PUBLISHED doi={res['doi']} url={res['record_url']}")
    _emit(res, args.output)
    return EXIT_OK


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="misty",
        description="Misty DOI — Muh Mitha Kijiye!\u2122  Automation-first DOI minting.",
    )
    p.add_argument("--version", action="version", version=f"misty-doi {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="write a metadata.json template")
    s.add_argument("-o", "--output", default="misty.json")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("validate", help="validate a canonical metadata file")
    s.add_argument("-m", "--metadata", required=True)
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("transform", help="emit zenodo/datacite/codemeta/CFF")
    s.add_argument("-m", "--metadata", required=True)
    s.add_argument("-o", "--outdir", default="build")
    s.set_defaults(func=cmd_transform)

    s = sub.add_parser("package", help="build an offline doi-package directory")
    s.add_argument("-m", "--metadata", required=True)
    s.add_argument("-f", "--files", nargs="+", required=True)
    s.add_argument("-o", "--outdir", default="doi-package")
    s.add_argument("--doi", default=None, help="embed a pre-known DOI")
    s.add_argument("--output", default=None, help="also write manifest to this path")
    s.set_defaults(func=cmd_package)

    s = sub.add_parser("ots", help="OpenTimestamps stamp/verify/upgrade")
    s.add_argument("action", choices=["stamp", "verify", "upgrade"])
    s.add_argument("path")
    s.set_defaults(func=cmd_ots)

    s = sub.add_parser(
        "publish",
        help="one-shot: validate + package + Zenodo deposit/upload/publish -> DOI",
    )
    s.add_argument("-m", "--metadata", required=True)
    s.add_argument("-f", "--files", nargs="+", required=True)
    s.add_argument("--token", default=None, help="override ZENODO_TOKEN (discouraged)")
    s.add_argument("--sandbox", action="store_true",
                   help="use sandbox.zenodo.org (also via ZENODO_SANDBOX=1)")
    s.add_argument("--no-publish", action="store_true",
                   help="create + upload + set metadata but leave as draft")
    s.add_argument("--dry-run", action="store_true",
                   help="package locally, make no network calls")
    s.add_argument("--no-package", action="store_true",
                   help="skip building the offline doi-package")
    s.add_argument("--package-dir", default="doi-package")
    s.add_argument("--output", default=None, help="write result.json here too")
    # If --sandbox flag absent, fall back to env inside ZenodoClient.
    s.set_defaults(func=cmd_publish, sandbox=None)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # For publish, --sandbox absent => None so ZenodoClient consults the env.
    try:
        return args.func(args)
    except MistyError as exc:
        _log(f"ERROR: {exc}")
        return exc.code
    except FileNotFoundError as exc:
        _log(f"ERROR: {exc}")
        return 2
    except KeyboardInterrupt:
        _log("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
