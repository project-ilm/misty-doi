# Open source, for collaborators (human or AI)

© 1993–2026 Abhishek Choudhary. All rights reserved (this document).
Text is CC-BY-SA-4.0. The linked works belong to their authors and are cited below.

You do not need to invent open-source practice from scratch, and this project
does not try to. Where a mature community has already written the guidance, we
**link and attribute it** rather than paraphrase or copy it. What follows is a
map: each entry is a one- or two-line summary in our own words, the authority
that produced it, and where to read the real thing. Read the source, not the
summary, before you rely on it.

Nothing here is legal advice. For anything with legal weight — licence choice,
compliance, patents — the source materials say, correctly, to involve counsel.

---

## Running an open-source programme

- **TODO Group — Guides and Resources.** The reference body of practice for
  Open Source Program Offices: strategy, compliance, releasing code, measuring
  health, community. Openly licensed (CC-BY-4.0). — TODO Group.
  <https://todogroup.org/guides/>
- **TODO Group — OSPO Definition.** A shared, citable definition of what an OSPO
  is and does, so we use one vocabulary. — TODO Group.
  <https://github.com/todogroup/ospodefinition.org>
- **The OSPO Book.** Book-length treatment of structure, strategy and
  compliance. — TODO Group. <https://ospobook.todogroup.org/>
- **Starting an Open Source Program Office.** A short, leadership-facing
  overview. — The Linux Foundation, with the TODO Group.
  <https://www.linuxfoundation.org/resources/open-source-guides/setting-an-open-source-strategy>
- **A Guide to Outbound Open Source Software.** How to release code outward
  cleanly — the guide most relevant to this estate, which publishes constantly.
  — TODO Group. <https://todogroup.org/resources/guides/a-guide-to-outbound-open-source-software/>
- **CHAOSS.** Metrics and tooling for open-source project health, if we want to
  measure sustainability rather than guess at it. — CHAOSS / The Linux
  Foundation. <https://chaoss.community/>

## Licences and attribution hygiene

- **OSI approved licences.** The authoritative list of what "open source"
  licences actually are. — Open Source Initiative. <https://opensource.org/licenses/>
- **The Free Software Definition and the GNU licences.** The four freedoms, and
  the GPL/LGPL/AGPL family this estate uses. — Free Software Foundation.
  <https://www.gnu.org/philosophy/free-sw.html> · <https://www.gnu.org/licenses/>
- **SPDX License List.** Machine-readable licence identifiers — the
  `SPDX-License-Identifier:` tags we put at the top of files. — SPDX / The Linux
  Foundation. <https://spdx.org/licenses/>
- **REUSE.** A three-step standard for making every file's copyright and licence
  unambiguous and checkable. — Free Software Foundation Europe. <https://reuse.software/>

## Community and contribution

- **Contributor Covenant.** The code of conduct we adopt, rather than write. —
  Coraline Ada Ehmke; CC-BY-4.0. <https://www.contributor-covenant.org/>
- **GitHub — building community.** Practical templates for CONTRIBUTING, issue
  and PR flows aimed at individual contributors. — GitHub.
  <https://opensource.guide/> · <https://github.com/github/github-ospo>

---

## How this estate works, on top of that

The external guidance above is the *what*. These are the house rules that sit on
top of it — few, and enforced by machine so they do not rot:

1. **Retrieval before reconstruction.** Read the live repository. Do not rebuild
   from memory what already exists.
2. **Verification by execution.** Nothing is claimed unless a harness proves it,
   and the harness is itself mutation-tested.
3. **One intent per run.** A typed word plus a reason authorises a whole run.
4. **No donkey work.** The tooling performs every step itself; it never hands
   back a checklist.
5. **Corrections are canon.** A correction, once given, becomes a check.
6. **Nothing leaks.** Every deposit passes `misty guard` before it is minted —
   secrets, third-party PII, IPR markers, unverified metadata, un-clean-roomed
   standards and undisclosed inventions all block the mint.

Full text: `CONTRACT.md` and `CONTEXT.md` in `zistgah/governance`; working
practice in `dome/docs/PROCESS.md`.

---

## Seeding an issue as a collaborator (agile, and it scales)

Anyone — a person or another model — can add work through the process, not
around it. The unit is a **user story on a sprint board**, not a free-form note.

The board runs as lightweight Scrum:

- **Backlog** → **Ready** → **In sprint** → **In review (verify)** → **Done**.
- Each item carries a **worker** label (`ai:chatgpt`, `ai:gemini`, `ai:claude`,
  `ai:fable`, `human-only`), a **layer**, and its **blocks/blocked-by** links.
- A **sprint** is a GitHub milestone. Sprint length and ceremonies (planning,
  review, retro) are recorded as milestone description, so the cadence is data,
  not lore — which is what lets it scale past one person.
- "Done" means **verified**, not merely committed. The review column is where
  the executable check runs.

To seed one, open an issue using the **Story** template (below) and set the
worker label. That is the whole ceremony. Everything else — labels, the sprint
milestone, the board column — the tooling applies.

### Story template (`.github/ISSUE_TEMPLATE/story.md`)

```markdown
---
name: Story
about: A unit of work any collaborator (human or AI) can seed
title: ""
labels: []
---

## As a … I want … so that …
<one sentence: who benefits, what, and why>

## Acceptance (how we will know it is done)
- [ ] <observable, checkable outcome>
- [ ] verified by execution (name the check)

## Worker
<ai:chatgpt | ai:gemini | ai:claude | ai:fable | human-only>

## Layer
<governance | kernel | property | publication | infrastructure>

## Blocks / blocked by
<issue links, or "none">

## Clean-room / IPR
- [ ] if this implements a standard, a CLEANROOM.md will accompany it
- [ ] if this discloses an invention, a patent is cited or it is a defensive publication
```

---

## Clean-room, so people can learn a standard and apply it

If something is standard academic or engineering knowledge, a collaborator
should be free to **learn it and re-implement it** — that is how open knowledge
is meant to work. The discipline that keeps it clean is the clean-room: you
implement from the **public specification**, not from someone's copyrighted
implementation, and you write down that you did.

Ship a `CLEANROOM.md` with any deposit that implements a standard. `misty guard`
will ask for it, run an n-gram similarity check against any reference texts you
declare, and block the mint if the overlap is too high.

### `CLEANROOM.md` template

```markdown
# Clean-room record

**Artifact:** <name>
**Standard / prior art re-implemented:** <ISO / IEEE / RFC / paper + version>

## Specification used
Implemented from the PUBLIC specification only:
- <link to the public spec or standard>

## What was NOT used
- No copyrighted reference implementation was read while writing this.
- No code was copied from <name any implementations deliberately avoided>.

## Separation (if two-person clean-room)
- Specifier: <who read the prior art and wrote the spec summary>
- Implementer: <who wrote the code from that summary, without the prior art>

## Prior-art references declared for the similarity check
- <files/texts passed to `misty guard --reference` so overlap is measured, not assumed>

## Patents
- Relevant patents searched: <list, or "none found">
- This work: <cites patent X> | <is a defensive publication> | <n/a>

© 1993–2026 Abhishek Choudhary. All rights reserved.
```

---

*Attribution note:* the external works above are the property of their
respective authors and communities — the TODO Group, the Linux Foundation, the
Open Source Initiative, the Free Software Foundation, the Free Software
Foundation Europe, the SPDX and CHAOSS projects, Coraline Ada Ehmke, and GitHub.
They are linked, summarised and credited here, never reproduced. If any summary
misstates a source, the source is correct and this file is wrong — tell us and
we will fix it.
