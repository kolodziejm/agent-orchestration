---
name: promote-changes-to-prod
description: >-
  Ship an already reviewed pull request to production: merge it into develop,
  wait for CI, promote develop to master through a pull request, wait for the
  Railway deployment to succeed, then merge master back into develop. Use it only
  when the user explicitly asks to promote, ship, or release changes to
  production; never start it on your own initiative.
compatibility: Requires git, the GitHub CLI (gh), and the Railway CLI (railway), all authenticated, in a repository that uses develop and master branches and deploys master through Railway.
---

# Promote changes to prod

Take one reviewed pull request from its feature branch to production and leave
`develop` and `master` in sync. The user has already reviewed the pull request by
hand, so invoking this skill authorizes every merge and push listed below; do not
ask for confirmation between stages. It authorizes nothing else.

The stages run in order, and each one starts only after the previous one succeeded.
When a stage fails, stop there, leave the remaining stages undone, and report.

## Rules

- Never bypass a gate: no `--admin`, no force push, no skipped or disabled checks,
  no merge while a required check is failing or pending.
- Do not change code to make a check or a deployment pass. A failure is a result to
  report, not a problem to fix inside this skill.
- Never delete `develop` or `master`. Do not pass `--delete-branch` when merging the
  promotion pull request, because its head branch is `develop`.
- Use blocking commands (`gh pr checks --watch`, `gh run watch`) to wait. When
  polling is the only option, poll about every 30 seconds.
- The production branch is `master`. If the repository has no `master` but has
  `main`, use `main` everywhere below and say so in the report.

## 1. Preflight

- Find the pull request: the one the user named, otherwise the open pull request
  for the current branch (`gh pr view --json number,state,isDraft,baseRefName,headRefName,mergeable,url`).
- Stop if there is no open pull request, if it is a draft, if its base is not
  `develop`, or if it has merge conflicts.
- Confirm `gh auth status` succeeds and `railway status` shows a linked project and
  environment. Note which Railway services deploy from this repository's production
  branch; if that cannot be determined, ask the user once before merging anything.

## 2. Merge into develop

- Wait for the pull request's checks: `gh pr checks <number> --watch --fail-fast`.
- Merge it with the repository's usual method (look at how recent pull requests
  into `develop` were merged; default to `--squash` when there is no clear habit):
  `gh pr merge <number> --squash`.
- Record the resulting commit on `develop`:
  `gh pr view <number> --json mergeCommit --jq .mergeCommit.oid`.

## 3. Wait for CI on develop

- Find the workflow runs for that commit:
  `gh run list --branch develop --commit <sha> --json databaseId,name,status,conclusion`.
  Runs can take a minute to appear; retry for up to two minutes.
- Watch every run to the end: `gh run watch <run-id> --exit-status`.
- Continue only when every run concluded with success (skipped runs are fine).
- If no run appears, check whether any workflow triggers on pushes to `develop`.
  If none does, continue and state in the report that `develop` has no CI. If one
  should have run, stop.

## 4. Promote develop to master

- Reuse the open pull request from `develop` to `master` if one exists; otherwise
  create it:
  `gh pr create --base master --head develop --title "Promote develop to master" --body "<list of the pull requests being promoted>"`.
- If there is nothing to promote (`master` already contains `develop`), stop and
  report it.
- Wait for its checks: `gh pr checks <number> --watch --fail-fast`.
- Merge with a merge commit, so `master` keeps the history of `develop`:
  `gh pr merge <number> --merge`.
- Record the merge commit on `master`; this is the commit Railway must deploy.

## 5. Wait for the Railway deployment

- For each service that deploys from the production branch, list its deployments:
  `railway deployment list --service <service> --environment <environment> --json`.
  Check `railway deployment list --help` first if the installed CLI rejects a flag.
- Pick the deployment created for the recorded `master` commit (match the commit
  hash in the deployment metadata). Do not accept an older deployment that is
  already in `SUCCESS`. It can take a minute to appear; retry for up to five
  minutes, then stop and report that Railway started no deployment.
- Poll until the deployment reaches a final status. `SUCCESS` passes. `FAILED`,
  `CRASHED`, and `REMOVED` fail. `SKIPPED` means Railway decided the commit did not
  affect that service; treat it as passing and name it in the report.
- On failure, fetch the build and deploy logs (`railway logs --deployment <id>`,
  and `--build` for the build log), quote the lines that show the cause, and stop.
  Do not redeploy, roll back, or sync `develop` unless the user asks.

## 6. Sync develop with master

Run this stage only after every production deployment passed.

- `git fetch origin develop master`.
- If `origin/develop` is an ancestor of `origin/master`, fast-forward it without
  touching the working tree: `git push origin origin/master:develop`.
- Otherwise new commits reached `develop` during the promotion. Merge
  `origin/master` into `develop` in a clean checkout (a temporary worktree when the
  working tree has uncommitted changes), then push `develop`. Stop on a conflict
  and report the conflicting files.
- If the push is rejected by branch protection, open a pull request from `master`
  to `develop`, wait for its checks, and merge it with a merge commit.
- Verify: `git fetch origin` and then
  `git rev-list --count origin/develop..origin/master` prints `0`.

## Report

Finish with a short report:

- the pull request merged into `develop` and the promotion pull request, with links;
- the commit now on `master` and the Railway deployment status for each service;
- whether `develop` now contains `master`;
- on a stop: the stage that failed, the evidence (check name, log lines), and what
  was left undone, so the user knows exactly which state the branches are in.
