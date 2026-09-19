import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles"


class ProfileControlPlaneTests(unittest.TestCase):
    def test_profiles_are_versioned_and_openai_control_plane_is_explicit(self):
        profiles = {}
        for path in PROFILES.glob("*.toml"):
            with path.open("rb") as handle:
                profiles[path.stem] = tomllib.load(handle)

        self.assertNotIn("pi", profiles)
        self.assertGreaterEqual(len(profiles), 3)

        for name, profile in profiles.items():
            self.assertEqual(profile["version"], 1, name)
            control_plane = profile["control_plane"]
            self.assertEqual(set(control_plane), {"primary", "small_model", "builtins"}, name)
            self.assertEqual(set(control_plane["primary"]), {"model", "effort"}, name)
            self.assertIsInstance(control_plane["small_model"], str)
            self.assertEqual(set(control_plane["builtins"]), {"build", "plan"}, name)
            for builtin in control_plane["builtins"].values():
                self.assertEqual(set(builtin), {"model", "effort"}, name)
            supported = profile["capabilities"]["supported_variants"]
            expected_supported = (
                {"low", "high", "max"}
                if name in {"deepseek", "pi-glm"}
                else {"low", "medium", "high", "max", "xhigh"}
            )
            self.assertEqual(set(supported), expected_supported, name)

        openai = profiles["openai"]
        expected = {
            "primary": {"model": "openai/gpt-5.6-sol", "effort": "medium"},
            "small_model": "openai/gpt-5.6-luna",
            "builtins": {
                "build": {"model": "openai/gpt-5.6-sol", "effort": "medium"},
                "plan": {"model": "openai/gpt-5.6-sol", "effort": "high"},
            },
        }
        self.assertEqual(openai["control_plane"], expected)

        self.assertEqual(
            {
                role: (config["model"], config.get("variant"))
                for role, config in openai["models"].items()
            },
            {
                "worker": ("openai/gpt-5.6-luna", "high"),
                "worker-complex": ("openai/gpt-5.6-luna", "max"),
                "debugger": ("openai/gpt-5.6-sol", "high"),
                "explorer": ("openai/gpt-5.6-luna", "medium"),
                "validator": ("openai/gpt-5.6-luna", "medium"),
                "planner": ("openai/gpt-5.6-sol", "high"),
                "reviewer": ("openai/gpt-5.6-sol", "high"),
                "design-partner": ("openai/gpt-5.6-luna", "high"),
                "ux-critic": ("openai/gpt-5.6-luna", "high"),
            },
        )

        glm = profiles["pi-glm"]
        self.assertEqual(glm["control_plane"], {
            "primary": {"model": "zai/glm-5.3", "effort": "high"},
            "small_model": "zai/glm-5.3-flash",
            "builtins": {
                "build": {"model": "zai/glm-5.3", "effort": "high"},
                "plan": {"model": "zai/glm-5.3", "effort": "high"},
            },
        })
        sol_roles = {"debugger", "planner", "reviewer"}
        for role, config in glm["models"].items():
            expected_model = (
                "zai/glm-5.3"
                if role in sol_roles
                else "zai/glm-5.3-flash"
            )
            expected_variant = "max" if role == "worker-complex" else "high"
            self.assertEqual((config["model"], config["variant"]), (expected_model, expected_variant), role)

    def test_generators_reject_a_profile_with_missing_control_plane_effort(self):
        """This test will fail when a generator silently ignores incomplete control-plane intent."""
        generators = (
            ROOT / "harnesses" / "opencode" / "generate.py",
            ROOT / "harnesses" / "codex" / "generate.py",
            ROOT / "harnesses" / "claude-code" / "generate.py",
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            for name in ("harnesses", "policy", "profiles", "roles"):
                shutil.copytree(ROOT / name, repo / name)
            for profile_name in ("openai", "claude"):
                profile = repo / "profiles" / f"{profile_name}.toml"
                lines = profile.read_text().splitlines()
                lines.remove(next(line for line in lines if line.startswith("effort =")))
                profile.write_text("\n".join(lines) + "\n")

            for generator in generators:
                output = root / generator.parent.name
                command = [sys.executable, str(repo / generator.relative_to(ROOT)), "--output", str(output)]
                if generator.parent.name == "codex":
                    command.extend(["--profile", "openai"])
                result = subprocess.run(command, cwd=repo, text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0, generator)
                self.assertIn("control", result.stderr.lower(), generator)
                self.assertFalse(output.exists(), generator)

    def test_core_policy_defaults_to_delegation_with_a_narrow_direct_work_exception(self):
        """This test will fail when direct primary work is broader than the approved exception."""
        policy = (ROOT / "policy" / "orchestration.md").read_text()

        self.assertIn("Delegation is the default for repository discovery and source work.", policy)
        self.assertIn("small, clearly bounded, low-risk task", policy)
        self.assertIn("when delegation offers no concrete leverage", policy)
        self.assertIn("Before acting directly, the primary must briefly state why delegation is not useful.", policy)
        self.assertIn("broader discovery", policy)
        self.assertIn("multi-area or behavior-changing work", policy)
        self.assertIn("uncertain or context-heavy work", policy)
        self.assertIn("specialist", policy)
        self.assertIn("parallelism", policy)
        self.assertIn("independent risk separation", policy)
        self.assertIn("Delegated source-changing worker output always requires independent validator verification.", policy)
        self.assertIn("Independent ready mutation lanes may run in parallel", policy)
        self.assertIn("safe isolation", policy)
        self.assertIn("broad mechanical evidence gathering", policy)
        self.assertIn("only when independent evidence lanes provide concrete leverage", policy)
        self.assertIn("normally two and never more than four", policy)
        self.assertIn("one synthesis owner/writer", policy)
        self.assertIn("implementation validation remains serial", policy)
        self.assertIn("Handoffs, task instructions, workflow labels, schemas, acceptance contracts", policy)
        self.assertIn("requested by the user", policy)
        self.assertIn("`worker` and `worker-complex` may author or update tests", policy)
        self.assertIn("focused development tests and checks as `SELF-CHECKS`", policy)
        self.assertIn("`validator` independently reruns the smallest acceptance matrix", policy)

        for contradictory_wording in (
            "low- or medium-risk",
            "Everything else is non-trivial",
            "Apart from trivial work",
            "For a trivial inline edit as defined above",
            "After implementation, give `validator`",
        ):
            self.assertNotIn(contradictory_wording, policy)

    def test_reviewable_pr_delivery_contract_defines_coherence_fallback_and_checkpoint(self):
        """This fails when delivery can bypass cognitive coherence or non-blocking stack progress."""
        policy = (ROOT / "policy" / "orchestration.md").read_text()
        start = policy.index("## Reviewable-PR delivery contract")
        end = policy.index("## Implementation", start)
        def normalize(text):
            return " ".join(text.casefold().split())

        delivery = normalize(policy[start:end])

        for phrase in (
            "suitable hosting or remote support",
            "required capability and authorization",
            "pull requests are the default delivery and review unit",
            "equivalently reviewable local branch, commit, or patch",
            "must never claim that a remote action occurred",
            "one coherent reviewer question per PR",
            "observable behavior or directly removes complexity",
            "Line and file counts are diagnostics, not approval gates or hard ceilings",
            "reviewed generated artifact contributes to cognitive review burden",
            "Split when the unit contains independently valuable behavior",
            "answers more than one reviewer question",
            "unused scaffolding",
            "partial abstractions",
            "Infrastructure or abstraction work should be consumed by a real path in the same unit",
            "Coherence, executable evidence, and independent merge/review value outrank numeric optimization",
            "isolated, non-overlapping branches or worktrees",
            "promotion of PRs or fallback review units remains ordered",
            "user-approved named stack/ordered-unit plan authorizes uninterrupted execution",
            "no routine approval wait is required between those units",
            "automatically present the checkpoint below as a non-blocking progress report",
            "checkpoint does not authorize a merge, promotion, or remediation",
            "purpose and single concern",
            "behavior before and after",
            "key decisions and decomposition rationale",
            "human-authored diff statistics",
            "generated-artifact and lockfile statistics separately",
            "affected areas and files",
            "risks and mitigations",
            "validation evidence",
            "residual work",
            "next proposed PR or fallback review unit",
            "Completion reports and validation summaries must keep delivery status, diff accounting, and validation evidence distinct",
        ):
            self.assertIn(normalize(phrase), delivery)

        self.assertIn(normalize("Ask the user again only for a material scope or acceptance change"), delivery)
        self.assertNotIn(normalize("absolute ceiling"), delivery)
        self.assertIn(normalize("new risk or product decision"), delivery)
        self.assertIn(normalize("newly independent concern that changes decomposition"), delivery)
        self.assertIn(normalize("failed/BLOCKED validation that requires a decision"), delivery)
        self.assertIn(normalize("finding/remediation"), delivery)
        self.assertIn(normalize("merge authorization"), delivery)
        self.assertNotIn(normalize("wait for the user's explicit approval before proceeding"), delivery)
        self.assertNotIn(normalize("Approval for the initiative, an earlier slice, or an earlier checkpoint is not approval for the next one."), delivery)
        self.assertIn(normalize("This contract does not grant authority to create, push, or merge"), delivery)
        self.assertIn(normalize("This contract does not change the review-on-demand"), delivery)

    def test_ci_validates_pull_requests_and_main_pushes_without_duplicate_pr_pushes(self):
        """This fails when a pull-request branch also receives a duplicate push check."""
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("on:\n  pull_request:\n  push:\n    branches:\n      - main\n", workflow)
        self.assertNotIn("on:\n  push:\n  pull_request:", workflow)

    def test_planner_and_workers_define_reviewable_pr_slice_boundaries(self):
        """This fails when a plan or worker can silently widen a delivery slice."""
        contracts = {
            role: (ROOT / "roles" / f"{role}.md").read_text()
            for role in ("planner", "worker", "worker-complex")
        }
        planner = contracts["planner"]
        for phrase in (
            "## Reviewable-PR slice planning",
            "one coherent reviewer question, an observable outcome, and one bounded PR or fallback review unit",
            "expected accounting for human-authored maintained changed lines/files",
            "generated-artifact changed lines/files",
            "lockfile changed lines/files",
            "Line and file counts are diagnostics, not approval gates or hard ceilings",
            "independently valuable behavior",
            "unused scaffolding",
            "partial abstractions",
            "cognitive review burden",
            "checkpoint fields",
            "next proposed unit",
            "stop before expanding into a second independent concern",
            "user-approved named stack/ordered-unit plan",
            "next one to three implementation units",
            "revisable roadmap",
            "PR/fallback promotion remains ordered",
        ):
            self.assertIn(phrase, planner)

        for role, contract in contracts.items():
            for phrase in (
                "one coherent reviewer question",
                "human-authored maintained changed lines/files",
                "generated-artifact changed lines/files",
                "lockfile changed lines/files",
                "Line and file counts are diagnostics, not approval gates or hard ceilings",
                "non-blocking progress report",
                "Parallel implementation",
            ):
                self.assertIn(phrase, contract, role)
            self.assertIn("stack/ordered-unit plan", contract, role)
            if role in ("worker", "worker-complex"):
                self.assertIn("completion/readiness report", contract, role)
                self.assertIn("independent validation requested or evidence", contract, role)
            order_phrase = (
                "PR/fallback promotion remains ordered"
                if role == "planner"
                else "PR/fallback promotion remains ordered"
            )
            self.assertIn(order_phrase, contract, role)
            stop_phrase = "stop before expanding into a second independent concern"
            self.assertIn(stop_phrase.casefold(), contract.casefold(), role)
            delivery_phrase = (
                "create or push anything"
                if role == "planner"
                else "automatically create or push branches, commits, or PRs"
            )
            self.assertIn(delivery_phrase, contract, role)
            self.assertIn("claim that a remote action occurred", contract, role)

    def test_finding_authorization_boundary_allows_only_deterministic_in_scope_blockers(self):
        """REGRESSION CONTRACT: evidence, severity, and broad instructions never authorize new repair work."""
        policy = (ROOT / "policy" / "orchestration.md").read_text()
        for phrase in (
            "evidence/findings, never implementation authorization by themselves",
            "Severity labels, including `P0` or `Critical`, do not grant mutation authority.",
            "earlier broad instruction such as `act`, `proceed`, `fix`, or `implement`",
            "Only a deterministic, reproducible failure of an already-authorized acceptance criterion",
            "deterministic test/lint/typecheck/build/compile/format failure",
            "A validator `FAIL` is not automatically an acceptance blocker.",
            "One `debugger` -> `worker` -> `validator` repair cycle is allowed only for a validation failure classified as an acceptance blocker",
            "`BLOCKED`, infrastructure failures, missing prerequisites, nondeterministic observations",
            "duplicate rules/code, cleanup, refactors, quality improvements, newly proposed behavior, UX changes",
            "Critical security or data-loss findings must stop progress and be presented immediately.",
            "A P0/security finding from a reviewer or UX critic is a new finding requiring an individual decision",
            "If classification is uncertain, default to a finding and ask rather than auto-fix.",
        ):
            self.assertIn(phrase, policy)

    def test_individual_finding_decisions_are_done_skip_snooze_and_recorded(self):
        """REGRESSION CONTRACT: each non-blocker finding gets its own explicit outcome before repair."""
        policy = (ROOT / "policy" / "orchestration.md").read_text()
        for phrase in (
            "Before launching a repair worker for each non-blocker finding",
            "The individual `Done` / `Skip` / `Snooze` question must be self-contained enough that the user does not need to infer context",
            "Each actionable finding has a stable ID and exactly one recorded outcome.",
            "`Done` authorizes only that finding now; `Skip` declines it for this task; `Snooze` defers it",
            "question-count limit",
            "every finding remains a separate question and answer, never a package approval by default",
            "Record each outcome in the handoff and final synthesis",
            "do not re-propose a skipped finding in the same task unless evidence materially changes",
            "clear, structured explanation",
            "concrete problem or failure mode and evidence",
            "what it affects, including user-visible behavior, systems/components/files/contracts",
            "detailed viable solution options—not just labels",
            "implementation direction, scope/cost, trade-offs/risks",
            "recommendation with rationale where appropriate",
            "self-contained enough that the user does not need to infer context",
            "These are disposition decisions, not solution selection and not ambiguous package authorization.",
        ):
            self.assertIn(phrase, policy)
        self.assertGreaterEqual(policy.count("self-contained enough that the user does not need to infer context"), 2)
        self.assertGreaterEqual(policy.count("detailed viable solution options"), 2)
        self.assertNotIn("Prefer one single-choice question per actionable finding", policy)

    def test_role_contracts_make_finding_authorization_boundary_explicit(self):
        """REGRESSION CONTRACT: role outputs and repair handoffs cannot authorize unrelated findings."""
        contracts = {
            role: (ROOT / "roles" / f"{role}.md").read_text()
            for role in (
                "reviewer", "ux-critic", "planner", "debugger", "validator",
                "explorer", "worker", "worker-complex",
            )
        }
        self.assertIn("Reviewer output is evidence/findings only", contracts["reviewer"])
        self.assertIn("individual Done / Skip / Snooze decision", contracts["reviewer"])
        for phrase in (
            "concrete problem or failure mode and evidence",
            "user-visible behavior, systems/components/files/contracts",
            "detailed viable solution options, not just labels",
            "implementation direction, scope/cost, and trade-offs/risks",
            "recommend an option with rationale where appropriate",
            "self-contained user question",
        ):
            self.assertIn(phrase, contracts["reviewer"])
        self.assertIn("Validator output is evidence/findings only and never implementation authorization", contracts["validator"])
        self.assertIn("`FAIL` alone is insufficient", contracts["validator"])
        self.assertIn("Planning output is evidence, findings, and recommendations, not implementation authorization", contracts["planner"])
        self.assertIn("Debugger output is evidence/findings only, not implementation authorization", contracts["debugger"])
        self.assertIn("Explorer output is evidence/findings only and never mutation authority", contracts["explorer"])
        for role in ("worker", "worker-complex"):
            self.assertIn("exact acceptance blocker", contracts[role])
            self.assertIn("Broad directives such as `act`, `proceed`, `fix it`, or `implement`", contracts[role])
        self.assertIn("UX findings are always new findings requiring an individual user decision", contracts["ux-critic"])

    def test_role_contracts_separate_authoring_acceptance_and_heuristic_ux_audits(self):
        worker = (ROOT / "roles" / "worker.md").read_text()
        complex_worker = (ROOT / "roles" / "worker-complex.md").read_text()
        validator = (ROOT / "roles" / "validator.md").read_text()
        ux_critic = (ROOT / "roles" / "ux-critic.md").read_text()
        planner = (ROOT / "roles" / "planner.md").read_text()
        reviewer = (ROOT / "roles" / "reviewer.md").read_text()

        for contract in (worker, complex_worker):
            self.assertIn("author or update tests", contract)
            self.assertIn("focused development tests and checks as `SELF-CHECKS`", contract)
            self.assertIn("happy path before speculative hardening", contract)
            self.assertIn("never present self-checks as validator evidence", contract)
        self.assertIn("predefined deterministic acceptance", validator)
        self.assertIn("browser/device checks", validator)
        self.assertIn("`PASS`, `FAIL`, or `BLOCKED`", validator)
        self.assertIn("heuristic usability, accessibility, platform-fit, and parity", ux_critic)
        self.assertIn("explicitly requests or authorizes", ux_critic)
        self.assertIn("primary orchestrator", ux_critic)
        self.assertIn("Never run automatically after implementation, validation, or review", ux_critic)
        self.assertIn("target flow and named web/mobile surfaces", ux_critic)
        self.assertIn("already-running web URL", ux_critic)
        self.assertIn("already-prepared Appium session and device", ux_critic)
        self.assertIn("screenshot artifact destination", ux_critic)
        self.assertIn("physically traverse", ux_critic.casefold())
        self.assertIn("meaningful checkpoints", ux_critic)
        self.assertIn("native vision", ux_critic)
        self.assertIn("STATUS: BLOCKED", ux_critic)
        self.assertIn("Do not execute automated tests, lint, typecheck, formatters, builds", ux_critic)
        self.assertIn("mechanical release gate", ux_critic)
        self.assertIn("close implementation acceptance", ux_critic)

        routing = tomllib.loads((ROOT / "policy" / "routing.toml").read_text())
        self.assertEqual(routing["roles"]["ux-critic"]["edit"], "deny")
        self.assertEqual(routing["roles"]["ux-critic"]["bash"], "deny")
        orchestration = (ROOT / "policy" / "orchestration.md").read_text()
        self.assertIn("On-demand UX critic authorization and handoff", orchestration)
        self.assertIn("must never be launched automatically after implementation, validation, or review", orchestration)
        for contract in (planner, reviewer):
            self.assertIn("broad mechanical evidence gathering", contract)
            self.assertIn("only for genuinely independent evidence areas", contract)
            self.assertIn("otherwise use one focused explorer or targeted direct reads", contract)

    def test_generators_reject_unsupported_effort_without_querying_provider_catalogs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            for name in ("harnesses", "policy", "profiles", "roles"):
                shutil.copytree(ROOT / name, repo / name)
            for profile_name in ("openai", "claude"):
                profile = repo / "profiles" / f"{profile_name}.toml"
                lines = profile.read_text().splitlines()
                for index, line in enumerate(lines):
                    if line.startswith("variant ="):
                        lines[index] = 'variant = "provider-catalog-only"'
                        break
                profile.write_text("\n".join(lines) + "\n")

            generators = (
                ("opencode", ["harnesses/opencode/generate.py"]),
                ("codex", ["harnesses/codex/generate.py", "--profile", "openai"]),
                ("claude-code", ["harnesses/claude-code/generate.py"]),
            )
            for name, args in generators:
                output = root / name
                result = subprocess.run(
                    [sys.executable, *args, "--output", str(output)],
                    cwd=repo,
                    text=True,
                    capture_output=True,
                )
                self.assertNotEqual(result.returncode, 0, name)
                self.assertIn("unsupported", result.stderr.lower(), name)
                self.assertFalse(output.exists(), name)

    def test_generators_reject_effort_not_declared_by_the_selected_profile(self):
        """This test will fail when generators trust an unverified profile effort declaration."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            for name in ("harnesses", "policy", "profiles", "roles"):
                shutil.copytree(ROOT / name, repo / name)
            profile = repo / "profiles" / "openai.toml"
            lines = profile.read_text().replace(
                'supported_variants = ["low", "medium", "high", "max", "xhigh"]',
                'supported_variants = ["medium"]',
            )
            profile.write_text(lines)
            output = root / "output"
            result = subprocess.run(
                [
                    sys.executable,
                    str(repo / "harnesses" / "opencode" / "generate.py"),
                    "--output",
                    str(output),
                ],
                cwd=repo,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("supported", result.stderr.lower())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
