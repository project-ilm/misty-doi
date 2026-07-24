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
        "version": "1.0.1",
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



def cmd_newversion(args) -> int:
    """Add a version to an existing lineage instead of minting a new concept.

    `publish` always creates a brand-new record with a brand-new concept DOI.
    That is correct for a first deposit and wrong for everything after it. This
    command is the other half: it keeps the concept DOI and hangs a new version
    DOI beneath it, so a citation of the concept always resolves to the latest.

    The step people get wrong is files: a new-version draft arrives carrying the
    previous version's files. Uploading replacements without clearing leaves
    both in the record. `--replace-files` (the default) clears first.
    """
    m = metadata.load_validate_normalize(args.metadata)

    env_orcid = os.environ.get("ORCID")
    if env_orcid:
        for c in m["creators"]:
            c.setdefault("orcid", env_orcid)

    version = args.new_version or m.get("version")
    if not version:
        _log("ERROR: no version — pass --new-version or set `version` in the metadata")
        return 2
    m["version"] = version

    from .checksum import file_record
    file_records = [file_record(f) for f in args.files]
    for r in file_records:
        _log(f"sha256 {r['name']}: {r['sha256']}")

    if args.dry_run:
        _log(f"dry-run: would open a new version of {args.record} as {version}")
        _emit(result.build(deposition_id=None, bucket=None,
                           sandbox=bool(args.sandbox), files=file_records,
                           state="dry-run"), args.output)
        return EXIT_OK

    from .zenodo import ZenodoClient
    client = ZenodoClient(token=args.token, sandbox=args.sandbox)
    _log(f"target: {'SANDBOX' if client.sandbox else 'PRODUCTION'} ({client.base})")

    draft = client.new_version(int(args.record))
    dep_id = draft["id"]
    bucket = (draft.get("links", {}) or {}).get("bucket")
    concept = draft.get("conceptdoi") or (draft.get("metadata", {}) or {}).get("conceptdoi")
    _log(f"new version draft {dep_id} (concept {concept or 'unknown'})")

    if args.replace_files:
        n = client.clear_files(dep_id)
        _log(f"cleared {n} inherited file(s)")

    for f in args.files:
        info = client.upload_file(bucket, f)
        _log(f"uploaded {info.get('key', os.path.basename(f))}")

    client.set_metadata(dep_id, transform.to_zenodo(m))
    _log(f"metadata set (version {version})")

    if args.no_publish:
        _log("draft created; not publishing (--no-publish)")
        _log(f"discard with: misty discard {dep_id}")
        _emit(result.build(deposition_id=dep_id, bucket=bucket,
                           sandbox=client.sandbox, files=file_records,
                           concept_doi=concept, state="draft"), args.output)
        return EXIT_OK

    record = client.publish(dep_id)
    res = result.from_zenodo_record(record, sandbox=client.sandbox, files=file_records)
    res["previous_record"] = int(args.record)
    _log(f"PUBLISHED version doi={res['doi']} concept={res['concept_doi']}")
    _emit(res, args.output)
    return EXIT_OK


def cmd_discard(args) -> int:
    """Throw away an unpublished draft. The only undo Zenodo offers."""
    from .zenodo import ZenodoClient
    client = ZenodoClient(token=args.token, sandbox=args.sandbox)
    client.discard_draft(int(args.record))
    _log(f"discarded draft {args.record}")
    return EXIT_OK


def cmd_walk(args) -> int:
    """Walk every record the token can see and report what is wrong with it."""
    from . import audit
    rules = audit.load_rules(args.rules)

    if args.records:
        with open(args.records, "r", encoding="utf-8") as fh:
            records = json.load(fh)
        _log(f"reading {len(records)} record(s) from {args.records} (no network)")
    else:
        from .zenodo import ZenodoClient
        client = ZenodoClient(token=args.token, sandbox=args.sandbox)
        _log(f"target: {'SANDBOX' if client.sandbox else 'PRODUCTION'} ({client.base})")
        _log("listing depositions — Zenodo paginates, so this takes a few seconds")
        records = client.list_depositions(all_versions=not args.latest_only)
        _log(f"{len(records)} deposition(s) visible to this token")

    report = audit.walk(records, rules, repo_roots=args.repos or None)

    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    findings = sorted(report["findings"], key=lambda f: (order[f["severity"]], str(f["id"])))
    if not args.quiet:
        for f in findings:
            if f["severity"] == "INFO" and not args.verbose:
                continue
            print("  {sev:<5} {rid:<10} {doi:<26} {field:<28} {msg}".format(
                sev=f["severity"], rid=str(f["id"] or "-"),
                doi=(f["doi"] or "-")[:26], field=f["field"][:28], msg=f["message"]),
                file=sys.stderr)
            if f.get("observed") not in (None, ""):
                print(f"        observed: {f['observed']}", file=sys.stderr)

    c = report["counts"]
    _log(f"{report['published']} published, {report['drafts']} draft(s); "
         f"{c['ERROR']} error(s), {c['WARN']} warning(s), {c['INFO']} note(s)")
    if args.output:
        _emit(report, args.output)
    elif args.json:
        _emit(report, None)
    return 1 if c["ERROR"] and not args.no_fail else EXIT_OK



def cmd_harvest(args) -> int:
    """Pull the estate local, dedupe it, and assess every write-up."""
    from . import harvest
    if args.records:
        records = json.load(open(args.records, encoding="utf-8"))
        client = None
        _log(f"reading {len(records)} record(s) from {args.records} (no network)")
    else:
        from .zenodo import ZenodoClient
        client = ZenodoClient(token=args.token, sandbox=args.sandbox)
        _log(f"target: {'SANDBOX' if client.sandbox else 'PRODUCTION'} ({client.base})")
        _log("listing depositions — Zenodo paginates, so this takes a few seconds")
        records = client.list_depositions(all_versions=True)
        _log(f"{len(records)} deposition(s) visible")

    os.makedirs(args.outdir, exist_ok=True)
    json.dump(records, open(os.path.join(args.outdir, "records.json"), "w",
                            encoding="utf-8"), indent=2, ensure_ascii=False)

    dl = {"downloaded": [], "already_present": [], "failed": []}
    if client and not args.no_download:
        _log("downloading payloads — large deposits take a while; the terminal will")
        _log("look idle during each transfer. That is the download, not a hang.")
        dl = harvest.download(client, records, args.outdir)
        _log(f"{len(dl['downloaded'])} file(s) fetched, "
             f"{len(dl['already_present'])} already present, {len(dl['failed'])} failed")
        for doi, name, why in dl["failed"]:
            _log(f"  FAILED {doi} {name}: {why}")

    dd = harvest.dedupe(args.outdir, link=not args.no_link)
    _log(f"{dd['duplicate_groups']} duplicate group(s); "
         f"{dd['bytes_reclaimed']} bytes reclaimed by hard-linking")

    rows = harvest.assess(records)
    props = harvest.propose_links(records, min_shared=args.min_shared)

    if not args.quiet:
        print("\n  write-up assessment (lowest first)\n", file=sys.stderr)
        for r in rows:
            print("  %2d/%d  %-11s %-52s" % (r["score"], r["of"],
                  (r["doi"] or "-").split("/")[-1], (r["title"] or "")[:52]), file=sys.stderr)
            for miss in r["missing"]:
                print("         missing: %s" % miss, file=sys.stderr)
        print("\n  %d cross-reference(s) proposed (none applied)\n" % len(props), file=sys.stderr)
        for p in props[:args.show_links]:
            print("  %-11s -> %-11s  shares: %s" % (
                (p["from_doi"] or "-").split("/")[-1],
                (p["to_doi"] or "-").split("/")[-1],
                ", ".join(p["shared_terms"][:6])), file=sys.stderr)

    patch = harvest.patch_for(props)
    json.dump(patch, open(os.path.join(args.outdir, "crossref.proposed.json"), "w",
                          encoding="utf-8"), indent=2, ensure_ascii=False)
    report = {"tool": "misty-doi harvest", "records": len(records),
              "download": {k: len(v) for k, v in dl.items()},
              "dedupe": dd, "assessment": rows, "proposed_links": props}
    json.dump(report, open(os.path.join(args.outdir, "harvest.report.json"), "w",
                           encoding="utf-8"), indent=2, ensure_ascii=False)
    _log(f"payloads + reports under {args.outdir}")
    _log("crossref.proposed.json holds the suggested links — nothing was applied")
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

    s = sub.add_parser(
        "newversion",
        help="add a NEW VERSION to an existing record (keeps the concept DOI)",
        description="Unlike `publish`, this keeps the concept DOI and adds a "
                    "version beneath it. Use it for every deposit after the first.",
    )
    s.add_argument("-r", "--record", required=True,
                   help="deposition id of the LATEST published version")
    s.add_argument("-m", "--metadata", required=True)
    s.add_argument("-f", "--files", nargs="+", required=True)
    s.add_argument("--new-version", default=None,
                   help="version string for this release (else metadata.version)")
    s.add_argument("--replace-files", dest="replace_files", action="store_true",
                   default=True, help="clear inherited files first (default)")
    s.add_argument("--keep-files", dest="replace_files", action="store_false",
                   help="keep the previous version's files alongside the new ones")
    s.add_argument("--token", default=None)
    s.add_argument("--sandbox", action="store_true")
    s.add_argument("--no-publish", action="store_true")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--output", default=None)
    s.set_defaults(func=cmd_newversion, sandbox=None)

    s = sub.add_parser("discard", help="discard an unpublished draft")
    s.add_argument("record")
    s.add_argument("--token", default=None)
    s.add_argument("--sandbox", action="store_true")
    s.set_defaults(func=cmd_discard, sandbox=None)

    s = sub.add_parser(
        "walk",
        help="walk every Zenodo record this token can see and verify it",
        description="Reports; never edits. Exit 1 if any ERROR-class finding.",
    )
    s.add_argument("--rules", default=None, help="JSON rules file (see docs/WALK.md)")
    s.add_argument("--records", default=None,
                   help="read records from a JSON file instead of the network")
    s.add_argument("--repos", nargs="*", default=None,
                   help="local repository roots to scan for recorded DOIs")
    s.add_argument("--latest-only", action="store_true",
                   help="skip superseded versions (default walks all versions)")
    s.add_argument("--json", action="store_true", help="print the full report as JSON")
    s.add_argument("--output", default=None, help="write the report JSON here")
    s.add_argument("--quiet", action="store_true", help="counts only")
    s.add_argument("--verbose", action="store_true", help="include INFO findings")
    s.add_argument("--no-fail", action="store_true",
                   help="always exit 0 even with errors")
    s.add_argument("--token", default=None)
    s.add_argument("--sandbox", action="store_true")
    s.set_defaults(func=cmd_walk, sandbox=None)

    s = sub.add_parser(
        "harvest",
        help="pull every record's payload local, dedupe, assess the write-ups",
        description="Downloads, deduplicates by SHA-256, scores each abstract "
                    "against a reviewer's rubric and proposes cross-references. "
                    "Never edits a published record.",
    )
    s.add_argument("-o", "--outdir", default="doi-estate")
    s.add_argument("--records", default=None, help="read records from JSON, no network")
    s.add_argument("--no-download", action="store_true", help="metadata only")
    s.add_argument("--no-link", action="store_true", help="report duplicates, do not hard-link")
    s.add_argument("--min-shared", type=int, default=3,
                   help="shared terms before a cross-reference is proposed")
    s.add_argument("--show-links", type=int, default=25)
    s.add_argument("--quiet", action="store_true")
    s.add_argument("--token", default=None)
    s.add_argument("--sandbox", action="store_true")
    s.set_defaults(func=cmd_harvest, sandbox=None)

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
