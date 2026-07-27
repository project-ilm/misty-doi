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

from . import __version__, kit, masi, metadata, ots, package, result, transform
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

    if not _guard_gate(m, args.files, args):
        return 4
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



def _guard_gate(meta, files, args) -> bool:
    """Run the leakage guard before anything irreversible. Returns True to proceed.

    Fails closed: an ERROR-class finding stops the mint unless --allow-findings is
    passed with eyes open. WARN-class findings are printed and do not block.
    """
    if getattr(args, "no_guard", False):
        _log("guard: skipped (--no-guard)")
        return True
    from . import guard as _g
    rules = _g.DEFAULT_RULES
    if getattr(args, "guard_rules", None):
        rules = dict(rules); rules.update(json.load(open(args.guard_rules, encoding="utf-8")))
    refs = []
    for rp in (getattr(args, "reference", None) or []):
        try: refs.append(open(rp, encoding="utf-8", errors="replace").read())
        except OSError: _log(f"guard: reference not readable: {rp}")
    res = _g.scan_deposit(meta, files=[getattr(f, "name", f) for f in files] if files else None,
                          references=refs, rules=rules)
    for f in res["findings"]:
        _log("  guard %-5s %-10s %-14s %s %s" % (
            f["severity"], f["kind"], f["where"], f["message"],
            ("[" + f["sample"] + "]") if f["sample"] else ""))
    _log("guard: %d error(s), %d warning(s)" % (res["counts"]["ERROR"], res["counts"]["WARN"]))
    if not res["clear"] and not getattr(args, "allow_findings", False):
        _log("guard: ERROR-class findings block the mint. Fix them, or re-run with "
             "--allow-findings and a reason if you are certain they are false positives.")
        return False
    return True


def cmd_guard(args) -> int:
    """Scan a deposit for leakage without minting anything."""
    from . import guard as _g
    meta = metadata.load_validate_normalize(args.metadata) if args.metadata else json.load(open(args.json))
    rules = _g.DEFAULT_RULES
    if args.guard_rules:
        rules = dict(rules); rules.update(json.load(open(args.guard_rules, encoding="utf-8")))
    refs = [open(r, encoding="utf-8", errors="replace").read() for r in (args.reference or [])]
    res = _g.scan_deposit(meta, files=args.files or None, references=refs, rules=rules)
    for f in res["findings"]:
        print("  %-5s %-10s %-14s %s %s" % (f["severity"], f["kind"], f["where"],
              f["message"], ("[" + f["sample"] + "]") if f["sample"] else ""), file=sys.stderr)
    _log("%d error(s), %d warning(s); %s" % (
        res["counts"]["ERROR"], res["counts"]["WARN"],
        "CLEAR" if res["clear"] else "BLOCKED"))
    if args.output:
        _emit(res, args.output)
    return 0 if res["clear"] else 1


def cmd_kit(args) -> int:
    """Build a ready-to-mint kit per author from a record list."""
    with open(args.records, encoding="utf-8") as fh:
        doc = json.load(fh)
    rows = doc
    if isinstance(doc, dict):
        key = args.records_path or next(
            (k for k in ("records", "items", "entries", "posts") if isinstance(doc.get(k), list)),
            None,
        )
        if key is None:
            raise MistyError("no record list found; pass --records-path")
        rows = doc[key]

    grouped = kit.group_records(rows, author_key=args.group_by)
    if not grouped:
        raise MistyError("no attributed records — every row lacks %r" % args.group_by)

    os.makedirs(args.outdir, exist_ok=True)
    entries = []
    for author, arts in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        for a in arts:
            if args.proofs_from and a.get("sha256"):
                stem = a["sha256"][: args.proof_prefix]
                cand = os.path.join(args.proofs_from, f"{stem}.sha256.ots")
                a["proof"] = cand if os.path.exists(cand) else None
        draft = {
            "title": args.title_template.format(author=author, n=len(arts)),
            "upload_type": args.upload_type,
            "description": args.description_template.format(author=author, n=len(arts)),
            "license": args.license,
            "language": args.language,
            "creators": [{"name": author, "affiliation": "", "orcid": ""}],
            "keywords": args.keywords or [],
        }
        if args.related:
            draft["related_identifiers"] = [
                {"identifier": args.related, "relation": "isDerivedFrom", "scheme": "url"}
            ]
        entries.append(
            kit.build_kit(
                args.outdir,
                author,
                draft,
                arts,
                proofs_from=args.proofs_from,
                strict_verify=not args.no_verify_gate,
            )
        )

    idx = kit.write_index(args.outdir, entries)
    skipped = sum(1 for r in rows if not (r.get(args.group_by) or "").strip())
    _log(f"{len(entries)} kits in {args.outdir}; {skipped} unattributed records got none")
    _emit({"kits": len(entries), "index": idx, "unattributed": skipped,
           "entries": entries}, args.output)
    return EXIT_OK


def cmd_masi(args) -> int:
    """MASI workflows: concept to persistent scholarly artifact."""
    root = args.root
    act = args.action

    if act == "tracks":
        for name in sorted(masi.TRACKS):
            t = masi.TRACKS[name]
            _log(f"{name:<12} {t['label']}")
            _log("             " + " -> ".join(t["states"]))
            _log("             " + t["note"])
        return EXIT_OK

    if act == "new":
        m = masi.new(args.slug, args.track, args.title or "", root, args.link or [])
        if args.set: m = masi.set_facts(m, args.set); masi.save(m, root)
        _log(f"{m['slug']} created on track {m['track']!r} at {m['state']!r}")
        _emit(m, args.output)
        return EXIT_OK

    if act == "list":
        ms = masi.all_matters(root)
        if not ms:
            _log(f"no matters under {root}/")
        for m in ms:
            ok, errs = masi.mintable(m, root)
            _log(f"{m['slug']:<28} {m['track']:<11} {m['state']:<22} "
                 f"{'' if ok else 'BLOCKED: ' + errs[0]}")
        _emit(ms, args.output)
        return EXIT_OK

    m = masi.load(args.slug, root)

    if act == "status":
        _log(masi.render(m, root)); _emit(m, args.output); return EXIT_OK

    if act == "set":
        m = masi.set_facts(m, args.set or []); masi.save(m, root)
        _log(f"{m['slug']}: " + ", ".join(f"{k}={v}" for k, v in sorted(m["facts"].items())))
        _emit(m, args.output); return EXIT_OK

    if act == "link":
        for s in args.link or []:
            if s not in m["links"]: m["links"].append(s)
        masi.save(m, root)
        _log(f"{m['slug']} links: " + ", ".join(m["links"]))
        _emit(m, args.output); return EXIT_OK

    if act == "state":
        if args.set: m = masi.set_facts(m, args.set)
        m = masi.advance(m, args.to, args.note or "", root, args.force)
        _log(f"{m['slug']} -> {m['state']}")
        for i, sev, msg in masi.gates(m, root):
            if sev != "ok": _log(f"  {sev} {i}: {msg}")
        _emit(m, args.output); return EXIT_OK

    if act == "review":
        m = masi.add_review(m, args.round, args.decision, args.reviewer or "",
                            args.note or "", args.received_on or "", root)
        _log(f"{m['slug']}: round {args.round} {args.decision}")
        _emit(m, args.output); return EXIT_OK

    if act == "gate":
        rows = masi.gates(m, root)
        for i, sev, msg in rows:
            _log(f"{sev:<5} {i:<3} {msg}")
        ok, errs = masi.mintable(m, root)
        _log("MINTABLE" if ok else "BLOCKED")
        _emit({"slug": m["slug"], "mintable": ok, "gates":
               [{"id": i, "severity": s, "message": g} for i, s, g in rows]}, args.output)
        return EXIT_OK if ok else EXIT_ERROR

    raise MistyError(f"unknown masi action {act!r}")


def cmd_latest(args) -> int:
    """Print the deposition id of the latest PUBLISHED version of a concept.

    Removes the donkey work of hunting the id by hand before `newversion`.
    """
    from .zenodo import ZenodoClient
    client = ZenodoClient(token=args.token, sandbox=args.sandbox)
    want = str(args.concept).strip().split("/")[-1]     # accept DOI or bare id
    deps = client.list_depositions(all_versions=True)
    pub = [d for d in deps
           if (d.get("state") == "done" or d.get("submitted"))
           and (str((d.get("conceptrecid") or "")) == want
                or (d.get("conceptdoi") or "").endswith(want)
                or str(d.get("id")) == want)]
    if not pub:
        _log(f"no published version found for concept {args.concept}")
        return 1
    latest = max(pub, key=lambda d: d.get("id", 0))
    print(latest["id"])
    _log(f"latest published version of {args.concept}: deposition {latest['id']} "
         f"(doi {latest.get('doi')})")
    return 0


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
    s.add_argument("--no-guard", action="store_true", help="skip the leakage guard (not advised)")
    s.add_argument("--allow-findings", action="store_true", help="proceed despite guard ERRORs")
    s.add_argument("--guard-rules", default=None, help="JSON overriding guard rules")
    s.add_argument("--reference", nargs="*", default=None, help="reference texts for the plagiarism check")
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

    s = sub.add_parser("guard", help="scan a deposit for secrets, PII, IPR leakage, "
                                     "clean-room and patent issues — no mint")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("-m", "--metadata", default=None)
    g.add_argument("--json", default=None, help="raw metadata JSON (already Zenodo-shaped)")
    s.add_argument("-f", "--files", nargs="*", default=None)
    s.add_argument("--reference", nargs="*", default=None)
    s.add_argument("--guard-rules", default=None)
    s.add_argument("--output", default=None)
    s.set_defaults(func=cmd_guard)

    s = sub.add_parser(
        "kit",
        help="build a ready-to-mint kit per author (they mint, under their own token)",
    )
    s.add_argument("--records", required=True, help="JSON file holding the record list")
    s.add_argument("--records-path", default=None, help="key of the list inside that file")
    s.add_argument("--group-by", default="author", help="record field naming the author")
    s.add_argument("--outdir", default="author-kits")
    s.add_argument("--proofs-from", default=None, help="directory of existing .ots proofs")
    s.add_argument("--proof-prefix", type=int, default=16,
                   help="hex prefix length used to name proof files")
    s.add_argument("--license", default="cc-by-4.0")
    s.add_argument("--upload-type", default="publication")
    s.add_argument("--language", default="eng")
    s.add_argument("--keywords", nargs="*", default=None)
    s.add_argument("--related", default=None, help="source URL, recorded as isDerivedFrom")
    s.add_argument("--title-template", default="Collected works of {author}")
    s.add_argument("--description-template",
                   default="{n} items authored by {author}, listed with their addresses "
                           "and content digests. Drafted with machine assistance; the "
                           "author is responsible for scholarly accuracy.")
    s.add_argument("--no-verify-gate", action="store_true",
                   help="do not require the author to set author_verified before minting")
    s.add_argument("-o", "--output", default=None)
    s.set_defaults(func=cmd_kit)

    s = sub.add_parser("masi", help="MASI workflows: prereg, ethics, paper, journal, "
                                    "conference, chapter, patent")
    s.add_argument("action", choices=["new", "state", "review", "set", "link",
                                      "gate", "status", "list", "tracks"])
    s.add_argument("slug", nargs="?", default=None)
    s.add_argument("--track", choices=sorted(masi.TRACKS), default=None)
    s.add_argument("--title", default=None)
    s.add_argument("--to", default=None, help="state to move to")
    s.add_argument("--note", default=None)
    s.add_argument("--set", action="append", default=None, metavar="KEY=VALUE")
    s.add_argument("--link", action="append", default=None, metavar="SLUG")
    s.add_argument("--round", type=int, default=1)
    s.add_argument("--decision", choices=masi.REVIEW_DECISIONS, default=None)
    s.add_argument("--reviewer", default=None)
    s.add_argument("--received-on", dest="received_on", default=None)
    s.add_argument("--force", action="store_true", help="override a refused transition")
    s.add_argument("--root", default=masi.ROOT)
    s.add_argument("-o", "--output", default=None)
    s.set_defaults(func=cmd_masi)

    s = sub.add_parser("latest", help="print the latest published deposition id for a concept")
    s.add_argument("-c", "--concept", required=True, help="concept DOI or record id")
    s.add_argument("--token", default=None)
    s.add_argument("--sandbox", action="store_true")
    s.set_defaults(func=cmd_latest, sandbox=None)

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
