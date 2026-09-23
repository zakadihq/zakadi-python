# Contributing to zakadi-python

zakadi-python is open source under the Apache License 2.0 (`LICENSE`). The Zakadi name and logo
are trademarks that the licence does not cover (`NOTICE`). This file says how a change
gets in.

## Sign-off: the Developer Certificate of Origin

Contributions are accepted under the Developer Certificate of Origin 1.1
(https://developercertificate.org/), with no contributor licence agreement: a
contribution is licensed under the Apache License 2.0, the licence the project is
published under. Signing off a commit certifies the DCO for it. `git commit -s` adds the
sign-off, with your real name and the email address of the commit's author:

```text
Signed-off-by: Ada Lovelace <ada@example.com>
```

The sign-off, like every commit message, is ASCII only (the commit-msg hook refuses
anything else), so a name with accents or tone marks is written without them. A
contribution with a commit that is not signed off is not merged. Sign off commits
already made with `git rebase --signoff main`, then push again.

## Before the pull request

- For anything beyond a small fix, open an issue first, so the change is agreed before
  it is written.
- After cloning, install the git hooks: `lefthook install`. They run the same commands
  as CI (the ASCII check, the formatter and the linter on commit, the unit tests on
  push); they are never bypassed.
- Every file is ASCII only.
- A change a consumer can see adds a line under `[Unreleased]` in the package's
  `CHANGELOG.md`, in the group it belongs to; never a version or a release heading.
- Commit messages follow Conventional Commits, with a subject of at most 72
  characters. `Signed-off-by` is the only trailer: the commit-msg hook refuses
  `Co-authored-by` trailers and generated-by footers.
- A new dependency never carries an excluded licence: GPL or AGPL, SSPL or the Redis
  Source Available License, the FoxIO licence, or a non-commercial licence. The `lint`
  job reports the licence of every dependency, fails on an excluded one, and scans the
  dependencies for known vulnerabilities.

## The pull request

One change per pull request, against `main`. The title is `type(scope): one clause`, at
most 72 characters, without a trailing period. The body has these sections, in this
order:

```markdown
Closes #N

## What changed
The change and the reason for it, readable without the diff.

## Acceptance
- [x] **Each acceptance criterion of the issue, quoted**: the test, file or command
  that shows it.

## Verification
- `<command>`: <its final status line>

## Decisions
- Each choice the issue left open, the option taken and why; the licence of every new
  dependency.

## Not done
- Each omission with its reason, or: Nothing in scope was left undone.
```

The `format`, `lint`, `unit` and `integration` jobs pass before review. Pull requests
are rebase-merged, never squashed: each commit lands on `main` as it is, so each one
passes the hooks on its own.
