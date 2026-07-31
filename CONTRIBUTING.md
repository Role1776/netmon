<h1 align="center">Contributing to netmon</h1>

<p align="center">
  <b>How to get a change reviewed and merged without either of us losing an afternoon to it.</b>
</p>

---

netmon is a small project — roughly a thousand lines of Python across ten files, maintained in spare time. That size is the reason for most of the rules below: a change that would be routine in a large codebase can rewrite a meaningful fraction of this one, and a pull request that touches everything at once is effectively unreviewable here.

Contributions are welcome. The guidelines below are about **the shape of the pull request**, not about whether an idea is worth having.

> [!NOTE]
> These rules apply to code contributions. Typo fixes, documentation corrections, and small README improvements can ignore the size and scope limits entirely — just send them.

---

## The Rules in Short

| Rule | Limit |
| :--- | :--- |
| **One logical change per PR** | If the title needs the word "and", split it |
| **Size** | ≤ 300 new lines of code, excluding tests and documentation |
| **Independence** | Each PR branches from current `main` and contains only its own commits |
| **Open at once** | 2–3 pull requests maximum |
| **Compatibility** | Existing installs keep working after `git pull` with no manual steps |
| **Refactoring** | Its own PR, with no functional changes mixed in |
| **Verification** | CI green, plus a note in the description that you ran the bot |

Each of these is expanded below.

---

## 1. One PR, One Logical Change

A pull request should do exactly one thing, and its title should say what that thing is without needing a conjunction.

The most common violation is bundling a **schema change** together with the **code that uses it**. Those are two separate concerns with different risk profiles — a migration touches every existing database out there and is hard to undo, while the code reading the new columns is ordinary logic that can be reverted freely. Reviewing them together means reviewing the risky part while distracted by the boring part.

**Not acceptable — one PR:**

```text
Add mac/vendor/hostname columns to device_scans and extract them from nmap output
```

**Acceptable — two PRs:**

```text
PR 1: Add mac/vendor/hostname columns to device_scans
PR 2: Extract MAC/vendor/hostname from nmap output into the new columns
```

Other pairs that belong in separate pull requests:

* A bug fix and a new feature — even if you found the bug while building the feature.
* A new feature and the configuration plumbing for an unrelated setting.
* Changing report *content* and changing how reports are *delivered* (`tg.py` / `discord_hook.py`).
* Anything plus a drive-by cleanup of surrounding code (see [Refactoring](#6-refactoring-goes-in-its-own-pr)).

The test is simple: **if a reviewer might want to accept one half and reject the other, they are two pull requests.**

---

## 2. Size Limit: 300 Lines

**A pull request should add no more than ~300 lines of code.** Tests and documentation do not count toward the limit — write as many as the change deserves.

For a project this size, 300 lines is already a substantial change. If your diff is heading past it, that is almost always a signal that rule 1 has been broken and there are two or three changes in there waiting to be separated.

This is a guideline with a hard ceiling, not a precise budget. 320 lines for a genuinely single, cohesive feature is fine — just say so in the description. 700 lines is not, regardless of how cohesive it is, and it will be sent back to be split.

> [!TIP]
> Check before you open the PR: `git diff --stat main...HEAD`. If `main.py` alone is up by 300 lines, split it.

---

## 3. Pull Requests Must Be Independent

**Branch every pull request from the current `main`.** The diff of your PR must contain only your own commits — never the commits of another open pull request.

This is the rule most often broken by accident, usually by branching feature B off feature A's branch because A "isn't merged yet". The result is a pull request whose diff is mostly somebody else's unreviewed work, where there is no way to see what is actually new without reconstructing the branch history by hand. If seven pull requests each contain the previous six, there are not seven reviewable changes — there is one large one wearing seven hats.

**If a change genuinely builds on another one that is still under review, you have two options.**

### Option A — wait (preferred)

1. Open the PR that goes first (say, the schema migration). Nothing else.
2. Wait for it to be reviewed and merged.
3. `git fetch && git rebase origin/main` your follow-up work onto the new `main`.
4. Open the next PR.

Simplest for everyone, and the right default when the follow-up is not urgent.

### Option B — stack explicitly

If waiting is impractical, open the dependent PR with its **base branch set to the parent PR's branch**, not `main`, and note the dependency in the description (`Depends on #NN`).

GitHub then shows only your own changes in the diff — which is the entire point of this rule — and retargets the PR to `main` automatically once the parent is merged.

> [!IMPORTANT]
> Pull requests here are **squash-merged**, so the parent's commits are replaced by a single new commit when it lands. Your stacked branch still carries the originals, and will show duplicated changes and conflicts until you `git fetch && git rebase origin/main` it onto the squashed result. Expect one rebase per merged parent.

What is **not** acceptable under either option is a PR based on `main` whose diff contains another open PR's commits. That is the case this rule exists to prevent.

**Keep no more than 2–3 pull requests open at a time.** A queue of eleven open PRs that all touch the same main loop will conflict with each other no matter what order they merge in, and resolving that is work the maintainer did not sign up for.

> [!WARNING]
> **Don't force-push to a branch once review has started.** Rewriting history mid-review discards the review comments' context and makes it impossible to see what changed since the last look. Add new commits instead; they get squashed on merge anyway.

---

## 4. Don't Break Existing Installs

netmon is self-hosted. People run it unattended on a Raspberry Pi and pull updates occasionally. **After `git pull`, an existing install must keep working with no manual intervention.**

Concretely:

* **New environment variables must be optional**, with a sensible default in `config.py` and a commented-out entry in `.env.example`. A variable that must be set for the bot to start is a breaking change.
* **Never rename or repurpose an existing variable.** If `SLEEP_TIME` means seconds today, it means seconds forever.
* **Schema changes must migrate existing databases automatically.** An existing `metrics.sql` with months of history must survive the upgrade — no "delete your database and start over". Additive columns handled in `sqlite.py` at startup are the pattern to follow.
* **Don't change the shape of existing report output** without a reason stated in the PR description. People have grown used to the format, and the 24-hour graph is a trend record — a change in methodology shows up as a fake step change in the data.
* **Don't add new system dependencies** beyond `nmap` and `speedtest-cli` without discussing it in an issue first.

New behavior should be additive: off by default, or on by default only when it cannot surprise anyone.

---

## 5. Commits

Split code from documentation:

```text
Add connectivity heartbeat between speed test cycles
Document connectivity heartbeat between speed test cycles
```

Beyond that, keep commit messages in the imperative mood (`Add ...`, `Fix ...`, not `Added ...`), and describe what the commit does rather than which files it touched. Commits are squashed on merge, so a handful of clean ones is plenty — no need to rewrite history to reach exactly one.

---

## 6. Refactoring Goes in Its Own PR

If, while implementing something, you find code that wants restructuring — a function that has grown too long, a pattern duplicated three times, a helper worth extracting — **do not fix it in the same pull request**.

Open a separate PR that does the refactoring and **nothing else**: no new features, no behavior changes, no new configuration. A pure refactoring PR is easy to review, because the reviewer's only question is "does this do the same thing as before?". Mixed in with a feature, the same change is nearly impossible to review, because there is no way to tell which lines moved and which lines are new logic.

This also keeps the 300-line limit honest. "Half of this diff is just cleanup" is not an exemption — it is two pull requests.

If the refactoring is a prerequisite for your feature, submit it first and sequentially, per [rule 3](#3-pull-requests-must-be-independent).

---

## 7. Verify That It Actually Runs

### Automated checks

Every pull request runs [`.github/workflows/ci.yml`](.github/workflows/ci.yml). **It must be green before review.** Three things run there, and all of them run locally with the same commands:

| Check | Command | What it catches |
| :--- | :--- | :--- |
| **Lint** | `uv run ruff check .` | Undefined names, unused imports, broken `except` clauses |
| **Types** | `uv run pyright` | Type errors, per `pyrightconfig.json` |
| **Imports** | see workflow | Modules that fail to import on a clean checkout |

Install the tooling once with `uv sync --dev` — `ruff` and `pyright` are pinned in `pyproject.toml`, so your local run reports exactly what CI reports.

> [!NOTE]
> The ruff rule set is deliberately narrow (`E4`, `E7`, `E9`, `F`) — real mistakes only, no style enforcement. If you think a broader set is worth adopting, that is a fine proposal, but it goes in its own PR alongside the resulting fixes, not bundled into a feature.

CI is not a substitute for review, and a green run does not mean a change is in scope. All the rules above still apply.

### Running it for real

There is no test suite yet, so CI cannot tell you whether the bot actually works — only that the code is well-formed. So the minimum bar is still that **you ran the bot and it worked**, and that you say so in the pull request description.

```bash
uv run main.py
```

If your change touches the AI report, the graph, or notifier delivery, exercise that path rather than waiting for the normal 4-hour cadence — force a detailed report on the first cycle and confirm it arrives in Telegram or Discord.

If your change touches the database schema, **test it against a database that already has data in it**, not just a fresh one. A migration that works on an empty file and destroys real history is worse than no migration.

Tests are very welcome, and they do not count toward the size limit. If you want to add the first ones, that is a contribution in its own right — send it as a PR that adds tests and nothing else. The CI test job is already wired up: drop a `tests/` directory in and it starts gating on `pytest` automatically.

---

## 8. Pull Request Descriptions

Explain **why**, not **what** — the diff already covers what. A useful description answers:

* What problem does this solve, and how does it show up for someone running netmon?
* Why this approach rather than an obvious alternative?
* What did you run to verify it? (see [rule 7](#7-verify-that-it-actually-runs))
* Any new environment variables, with their defaults.
* Anything you deliberately left out of scope.

Two or three honest sentences beat a bulleted restatement of the diff.

---

## Before You Open a Pull Request

```text
[ ] One logical change — the title needs no "and"
[ ] ≤ ~300 new lines of code (git diff --stat main...HEAD)
[ ] Branched from current main; diff contains only my commits
[ ] No more than 2–3 of my PRs open at once
[ ] New env vars are optional, defaulted, and in .env.example
[ ] Existing databases and configs still work untouched
[ ] No unrelated refactoring mixed in
[ ] uv run ruff check . && uv run pyright — both clean
[ ] Ran the bot; said so in the description
[ ] Description explains why, not what
```

---

## Larger Ideas

For anything substantial — a new subsystem, a change to the report architecture, a new dependency — **open an issue first** and describe the idea before writing the code. It is a much cheaper conversation than a 700-line pull request that gets sent back to be split into five.

This is not a gate on ambition. Big ideas are fine; they just need to arrive as a sequence of small pull requests, and agreeing on the shape of that sequence up front saves everyone the rework.

---

## License

By contributing, you agree that your contributions are licensed under the **MIT License**, the same as the rest of the project. See [`LICENSE`](LICENSE).
