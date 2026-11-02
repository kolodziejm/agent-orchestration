---
name: review-triage
description: >-
  Review a pull request, branch, or working-tree diff for defects, verify each
  finding, rate it critical, high, medium, low, or nit against a fixed rubric, and
  give a merge recommendation. Post the findings as inline pull request comments
  only when the user asks, and on a later run update the earlier review instead of
  posting it again. Use it when the user asks to review a change and wants the
  findings ranked by severity, triaged before merge, or checked again after a push.
compatibility: Reviewing works on any git diff. Reading or commenting on a pull request needs the GitHub CLI (gh), authenticated.
---

# Review triage

Find what is wrong with a change, check each finding against the code, rate it
with the rubric below, and say what must be fixed before merge. The rating
matters as much as the finding: a reader should be able to act on the table
alone.

## Rules

- Report only findings you checked against the code. A finding you could not
  confirm stays in the list, marked unconfirmed, with the condition that would
  confirm it and the severity it would have then.
- Rate the impact the change has where it ships. A feature gate or flag lowers
  the impact only while it is off for real users. Name the gate and the severity
  the finding would have once the gate is on.
- Read the target repository's agent instructions (`AGENTS.md`, `CLAUDE.md`, and
  the docs they point to). A broken repository rule is a finding: quote the rule.
  Rate it by what breaking the rule causes, not by the fact that it is a rule.
- Do not change code, push, or comment on the pull request unless the user asked
  for it in this request.

## 1. Collect the change

- Pull request: `gh pr view <ref> --json number,headRefOid,headRefName,baseRefName,files,body`
  and `gh pr diff <ref>`. Record the head commit; every comment you post is pinned
  to it.
- Branch: `git diff <base>...<branch>`, with the base from the user or the
  repository's default branch.
- Working tree: `git diff HEAD`, plus any new files that are not yet tracked.
- Read the pull request description and any TODO list in it. A claim there that
  the code contradicts is a finding.
- For a pull request, check whether an earlier `review-triage` review exists
  (step 7). If one does, this run is a re-review.

## 2. Find

- If the harness has a review command or a read-only reviewer agent, use it to
  produce candidate findings. Give it the diff and the repository's agent
  instructions, not your own conclusions.
- Otherwise review the diff yourself, looking for, in this order: correctness and
  security, failure handling, behaviour across the states a user can be in (signed
  in, signed out, expired session, gate on or off, mobile), performance on the
  main path, broken repository rules, then duplication and dead code.
- Check repository metadata the change touches, such as CODEOWNERS
  (`gh api repos/<owner>/<repo>/codeowners/errors?ref=<head branch>`), routing,
  service configuration, and feature gate ownership.

## 3. Verify

For each candidate finding, open the code it points to and confirm the failure
scenario: the input or state, the path it takes, and the wrong result. Drop
findings that do not hold up. Mark a finding unconfirmed when its trigger depends
on something you could not check, such as runtime configuration or another
repository.

## 4. Rate

| Severity | Use when |
| --- | --- |
| Critical | Users or data are harmed now, or will be as soon as the change ships: data loss or corruption, an exploitable security hole, an outage, payments or bookings broken for everyone affected. No gate protects it. |
| High | A realistic user path fails, or a security weakness needs an unusual but reachable condition. Fix before merge. |
| Medium | A less common path fails or degrades with no recovery, or a process safeguard is missing with a real consequence (no code owner, no alert, no rollback). Usually fix before merge. |
| Low | It works, but is slower, harder to change, or breaks a repository rule with a concrete cost. Fix soon or in a follow-up. |
| Nit | Style, naming, consistency, or duplication that has not yet caused a difference. Optional. |

When a finding falls between two levels, pick the lower one and give the reason
in one clause.

## 5. Report

Lead with the merge recommendation in one sentence: which findings to fix before
merge, and whether the rest can follow up. Then give one table sorted by
severity:

| # | Severity | Finding (`file:line`) | Why this severity |

Then list unconfirmed findings with the condition that would confirm each one.
On a re-review, also list which earlier findings were fixed and which are still
open. Keep each row short; the failure scenario goes in the posted comment, not
the table.

## 6. Post (only when the user asks)

- Post one review, not separate comments: `POST repos/<owner>/<repo>/pulls/<n>/reviews`
  with `commit_id` set to the recorded head commit, `event: COMMENT`, and one
  comment per finding (`path`, `line`, `side: RIGHT`). The review body is the
  merge recommendation and the table, and its first line is the marker
  `<!-- review-triage -->`.
- Before posting, check that every anchor line is an added or context line in that
  file's patch. A line outside the diff makes GitHub reject the whole review with
  a 422 error. Move a finding whose line is outside the diff into the review body.
- Start each comment with its severity in bold, then the defect, the failure
  scenario, and a fix when it fits in a few lines.
- Put team names, handles, and placeholders in backticks so posting notifies
  nobody.
- Use `event: REQUEST_CHANGES` only if the user asks for it.
- Report the review URL and how many comments landed inline or in the body.

## 7. Re-review after a push

An earlier review is one whose body contains `<!-- review-triage -->` and whose
author is the authenticated user (`gh api user --jq .login`). Its comments are
the threads it started. Read them with GraphQL, since only GraphQL exposes thread
ids and resolution:

```
gh api graphql -F owner=<owner> -F repo=<repo> -F number=<n> -f query='
query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){
pullRequest(number:$number){reviewThreads(first:100){nodes{id isResolved isOutdated
comments(first:50){nodes{databaseId author{login} body path line
pullRequestReview{databaseId body}}}}}}}}'
```

Review the new head commit as in steps 1–4, then match each earlier finding to
the new results by file and defect, not by line number:

- **Fixed:** the defect no longer reproduces. Reply in the thread
  "Fixed in `<short sha>`." and resolve it with the `resolveReviewThread`
  mutation, but only if the thread is still open and nobody else has replied
  disputing the finding. A disputed thread stays open and goes in the report.
- **Still open:** do not post it again. If its severity changed, reply in the
  thread with the new severity and the reason. If the thread is outdated because
  the code moved, reply with the new `file:line`.
- **New:** post as in step 6.

Post the new findings and the updated table as one new review with the marker.
Never edit or delete earlier comments, and never touch threads `review-triage`
did not start. If the user has not asked to post, only report the fixed, open,
and new findings.
