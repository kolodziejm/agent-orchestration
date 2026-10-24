#!/usr/bin/env python3
"""Audit Claude Code transcripts: token usage, spawns, and per-run verification effort.

Reads the session transcripts Claude Code keeps under `~/.claude/projects`
(`<project>/<session>.jsonl` for the main agent and
`<project>/<session>/subagents/agent-<id>.jsonl` plus `.meta.json` for every
subagent run) and writes aggregate and per-run data as JSON files outside this
repository. See audit/README.md.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11 or newer is required (tomllib).")

import argparse
import collections
import datetime
import json
import os
import re
import statistics
import tomllib
from pathlib import Path

DEFAULT_PROJECTS_DIR = "~/.claude/projects"
DEFAULT_OUT_ROOT = "~/.local/state/agent-orchestration/audits"
TOKEN_KINDS = ("input", "output", "cache_read", "cache_creation")
# Relative cost units, model-agnostic: input 1, cache write 1.25, cache read 0.1, output 5.
WEIGHTS = {"input": 1.0, "cache_creation": 1.25, "cache_read": 0.1, "output": 5.0}
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
SPAWN_TOOLS = frozenset({"Agent", "Task"})
DEFAULT_IMPLEMENTATION_AGENTS = ("worker", "worker-complex")
UNSPECIFIED = "unspecified"
MAX_PROMPT_CHARS = 6000
MAX_REPORT_CHARS = 1500

# Bash commands that count as verification of any kind (the original audit's test/build/lint filter).
DEFAULT_VERIFICATION = r"test|jest|vitest|pytest|tsc|lint|build|xcodebuild|expo|gradle"
# A command matching one of these is a full gate, whatever else it names.
DEFAULT_FULL_GATE = (
    r"\bweb:check\b",
    r"\bi18n:check\b",
    r"(^|[\s/])scripts/check\b",
)
# A command matching one of these runs a test suite: a full gate unless a targeted marker also matches.
DEFAULT_RUNNERS = (
    r"\b(jest|vitest|pest)\b",
    r"\bartisan\s+test\b",
    r"\bcargo\s+test\b",
    r"\bpytest\b",
    r"\bpython[\d.]*\s+-m\s+(unittest|pytest)\b",
    r"\b(npm|pnpm|yarn|bun)\s+(run\s+)?test\b",
)
# A runner command matching one of these names a file, a test, or a package, so it is targeted.
DEFAULT_TARGETED = (
    r"\S+\.(test|spec)\.[cm]?[jt]sx?\b",
    r"\S*Test\.php\b",
    r"\btest_\w+\.py\b",
    r"\b\w+_test\.(py|go|rs)\b",
    r"(^|\s)\S*tests?/\S+",
    r"--filter\b",
    r"--testNamePattern\b",
    r"--testPathPattern\b",
    r"--findRelatedTests\b",
    r"--related\b",
    r"--changedSince\b",
    r"(^|\s)-t\s",
    r"(^|\s)-k\s",
    r"\bcargo\s+test\b.*(\s-p\s|--package\b|--lib\b|--test\s|--bin\s|\s--\s+\w)",
)


class AuditError(Exception):
    """A usage problem the CLI reports without a traceback."""


# ---------------------------------------------------------------------------
# Command classification
# ---------------------------------------------------------------------------


class CommandClassifier:
    """Sorts Bash commands into full gates, targeted test runs, and other verification."""

    def __init__(self, full_gate=DEFAULT_FULL_GATE, runners=DEFAULT_RUNNERS, targeted=DEFAULT_TARGETED,
                 verification=DEFAULT_VERIFICATION):
        self.full_gate = [re.compile(p) for p in full_gate]
        self.runners = [re.compile(p) for p in runners]
        self.targeted = [re.compile(p) for p in targeted]
        self.verification = re.compile(verification, re.IGNORECASE)

    def classify(self, command: str) -> str | None:
        """`full`, `targeted`, or None; a command counts once, and a full gate wins."""
        if not command:
            return None
        if any(p.search(command) for p in self.full_gate):
            return "full"
        if any(p.search(command) for p in self.runners):
            return "targeted" if any(p.search(command) for p in self.targeted) else "full"
        return None

    def is_verification(self, command: str) -> bool:
        return bool(command) and (self.classify(command) is not None or bool(self.verification.search(command)))


def load_config(path: str | None) -> dict:
    """The optional user config: `[commands]` regex lists and `[prices.<model>]` per million tokens."""
    if not path:
        return {}
    try:
        with open(os.path.expanduser(path), "rb") as handle:
            config = tomllib.load(handle)
    except OSError as error:
        raise AuditError(f"cannot read config {path}: {error}") from error
    except tomllib.TOMLDecodeError as error:
        raise AuditError(f"invalid config {path}: {error}") from error
    commands = config.get("commands", {})
    if not isinstance(commands, dict):
        raise AuditError("config: [commands] must be a table")
    for key in ("full_gate", "runners", "targeted"):
        value = commands.get(key)
        if value is not None and not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
            raise AuditError(f"config: commands.{key} must be a list of regular expressions")
        for pattern in value or []:
            try:
                re.compile(pattern)
            except re.error as error:
                raise AuditError(f"config: commands.{key}: bad regular expression {pattern!r}: {error}") from error
    if "verification" in commands:
        try:
            re.compile(commands["verification"])
        except (re.error, TypeError) as error:
            raise AuditError(f"config: commands.verification: {error}") from error
    prices = config.get("prices", {})
    if not isinstance(prices, dict):
        raise AuditError("config: [prices] must be a table")
    for model, table in prices.items():
        if not isinstance(table, dict) or not set(table) <= set(TOKEN_KINDS):
            raise AuditError(f"config: prices.{model} must be a table with keys from {', '.join(TOKEN_KINDS)}")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 for v in table.values()):
            raise AuditError(f"config: prices.{model} values must be non-negative numbers")
    return config


def classifier_from(config: dict, cli_full: list[str], cli_targeted: list[str]) -> CommandClassifier:
    commands = config.get("commands", {})
    for pattern in [*cli_full, *cli_targeted]:
        try:
            re.compile(pattern)
        except re.error as error:
            raise AuditError(f"bad regular expression {pattern!r}: {error}") from error
    full = list(cli_full) or commands.get("full_gate") or DEFAULT_FULL_GATE
    targeted = list(cli_targeted) or commands.get("targeted") or DEFAULT_TARGETED
    return CommandClassifier(
        full_gate=full,
        runners=commands.get("runners") or DEFAULT_RUNNERS,
        targeted=targeted,
        verification=commands.get("verification") or DEFAULT_VERIFICATION,
    )


class PriceTable:
    """USD per million tokens by model id; absent unless the user supplies a config file."""

    def __init__(self, prices: dict | None):
        self.prices = {model: {k: float(v) for k, v in table.items()} for model, table in (prices or {}).items()}
        self.unpriced: set[str] = set()

    def __bool__(self):
        return bool(self.prices)

    def lookup(self, model: str) -> dict | None:
        if model in self.prices:
            return self.prices[model]
        matches = [key for key in self.prices if model.startswith(key)]
        return self.prices[max(matches, key=len)] if matches else None

    def cost(self, model: str, usage: dict) -> float:
        table = self.lookup(model)
        if table is None:
            self.unpriced.add(model)
            return 0.0
        return sum(usage[kind] * table.get(kind, 0.0) for kind in TOKEN_KINDS) / 1_000_000


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def weighted(usage: dict) -> float:
    return sum(usage[kind] * WEIGHTS[kind] for kind in TOKEN_KINDS)


def zero() -> dict:
    return {"calls": 0, **{kind: 0 for kind in TOKEN_KINDS}}


def add(total: dict, usage: dict) -> None:
    total["calls"] += 1
    for kind in TOKEN_KINDS:
        total[kind] += usage[kind]


def percentile(values, q: float):
    values = sorted(values)
    if not values:
        return None
    index = (len(values) - 1) * q
    low = int(index)
    high = min(low + 1, len(values) - 1)
    return round(values[low] + (values[high] - values[low]) * (index - low), 1)


def median(values):
    return percentile(values, 0.5)


def parse_timestamp(value: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def resolve_timezone(name: str | None) -> datetime.tzinfo:
    if not name:
        return datetime.datetime.now().astimezone().tzinfo
    if name.upper() == "UTC":
        return datetime.timezone.utc
    try:
        import zoneinfo

        return zoneinfo.ZoneInfo(name)
    except Exception as error:  # unknown name or missing tz database
        raise AuditError(f"unknown time zone {name!r}: {error}") from error


def parse_day(value: str | None, flag: str) -> datetime.date | None:
    if value is None:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as error:
        raise AuditError(f"{flag} must be YYYY-MM-DD, got {value!r}") from error


def truncate(text: str | None, limit: int) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def home_relative(path: str) -> str:
    home = os.path.expanduser("~")
    return path.replace(home + os.sep, "", 1) if path.startswith(home + os.sep) else path


_TIMESTAMP = re.compile(r'"timestamp"\s*:\s*"([^"]+)"')


# ---------------------------------------------------------------------------
# Reading transcripts
# ---------------------------------------------------------------------------


def discover(projects_dir: Path):
    """Yield (path, project, session, is_subagent) for every transcript worth reading."""
    for path in sorted(projects_dir.glob("*/*.jsonl")):
        yield path, path.parent.name, path.stem, False
    for path in sorted(projects_dir.glob("*/*/subagents/*.jsonl")):
        yield path, path.parents[2].name, path.parents[1].name, True


def read_transcript(path: Path, project: str, session: str, is_subagent: bool) -> dict:
    meta: dict = {}
    if is_subagent:
        try:
            meta = json.loads(path.with_suffix(".meta.json").read_text())
        except (OSError, ValueError):
            meta = {}
    transcript = {
        "path": str(path), "project": project, "session": session, "is_subagent": is_subagent,
        "agent_id": path.stem if is_subagent else None, "meta": meta,
        "agent": (meta.get("agentType") or "unknown") if is_subagent else "main",
        "calls": {}, "tools": {}, "timestamps": [], "texts": [], "cwds": collections.Counter(),
    }
    with open(path, errors="replace") as handle:
        for line in handle:
            if '"assistant"' not in line:
                if is_subagent:
                    found = _TIMESTAMP.search(line)
                    if found:
                        transcript["timestamps"].append(found.group(1))
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            if record.get("timestamp"):
                transcript["timestamps"].append(record["timestamp"])
            if record.get("type") != "assistant":
                continue
            if record.get("cwd"):
                transcript["cwds"][record["cwd"]] += 1
            message = record.get("message") or {}
            usage = message.get("usage")
            model = message.get("model")
            if usage and model and model != "<synthetic>":
                message_id = message.get("id")
                key = (message_id, record.get("requestId")) if message_id else ("uuid", record.get("uuid"))
                call = {
                    "model": model, "ts": record.get("timestamp"),
                    "u": {
                        "input": usage.get("input_tokens") or 0, "output": usage.get("output_tokens") or 0,
                        "cache_read": usage.get("cache_read_input_tokens") or 0,
                        "cache_creation": usage.get("cache_creation_input_tokens") or 0,
                    },
                }
                old = transcript["calls"].get(key)
                if old is None or call["u"]["output"] >= old["u"]["output"]:
                    transcript["calls"][key] = call
            for block in message.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("id"):
                    transcript["tools"].setdefault(
                        block["id"], (block.get("name"), block.get("input") or {}, record.get("timestamp")))
                elif block.get("type") == "text" and (block.get("text") or "").strip():
                    transcript["texts"].append(block["text"])
    return transcript


def first_timestamp(transcript: dict) -> str:
    return min(transcript["timestamps"]) if transcript["timestamps"] else "z"


def load_transcripts(projects_dir: Path, modified_since: float | None = None) -> list[dict]:
    if not projects_dir.is_dir():
        raise AuditError(f"transcript directory not found: {projects_dir}")
    transcripts = []
    for path, project, session, is_subagent in discover(projects_dir):
        if modified_since is not None and path.stat().st_mtime < modified_since:
            continue
        transcripts.append(read_transcript(path, project, session, is_subagent))
    transcripts.sort(key=first_timestamp)
    return transcripts


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


class Window:
    """The inclusive local-day range an audit covers."""

    def __init__(self, since: datetime.date | None, until: datetime.date | None, tz: datetime.tzinfo):
        self.since, self.until, self.tz = since, until, tz

    def day_of(self, timestamp: str | None) -> str | None:
        if not timestamp:
            return None
        return parse_timestamp(timestamp).astimezone(self.tz).strftime("%Y-%m-%d")

    def contains(self, timestamp: str | None) -> bool:
        if self.since is None and self.until is None:
            return True
        day = self.day_of(timestamp)
        if day is None:
            return False
        value = datetime.date.fromisoformat(day)
        return (self.since is None or value >= self.since) and (self.until is None or value <= self.until)

    def modified_floor(self) -> float | None:
        if self.since is None:
            return None
        start = datetime.datetime.combine(self.since, datetime.time.min, tzinfo=self.tz)
        return (start - datetime.timedelta(days=1)).timestamp()


def dedupe_calls(transcripts: list[dict], window: Window) -> dict:
    """One record per API call across all transcripts: streaming repeats of a message keep the
    largest output, and the first transcript that saw the call owns it."""
    best: dict = {}
    for transcript in transcripts:
        for key, call in transcript["calls"].items():
            old = best.get(key)
            record = {**call, "project": transcript["project"], "session": transcript["session"],
                      "agent": transcript["agent"], "sub": transcript["is_subagent"]}
            if old is None or record["u"]["output"] >= old["u"]["output"]:
                if old is not None:
                    for field in ("project", "session", "agent", "sub"):
                        record[field] = old[field]
                best[key] = record
    return {key: record for key, record in best.items() if window.contains(record["ts"])}


def resolve_spawns(transcripts: list[dict]) -> list[dict]:
    """Every Agent/Task call once, with the type it ran as. A call without `subagent_type` takes
    the type the subagent's meta file records, else it is `unspecified`."""
    meta_types = {}
    for transcript in transcripts:
        if transcript["is_subagent"] and transcript["meta"].get("toolUseId"):
            meta_types[transcript["meta"]["toolUseId"]] = transcript["meta"].get("agentType")
    spawns: dict = {}
    for transcript in transcripts:
        for tool_id, (name, tool_input, timestamp) in transcript["tools"].items():
            if name in SPAWN_TOOLS and tool_id not in spawns:
                declared = tool_input.get("subagent_type")
                spawns[tool_id] = {
                    "id": tool_id, "ts": timestamp, "declared": declared,
                    "type": declared or meta_types.get(tool_id) or UNSPECIFIED,
                    "caller": "subagent" if transcript["is_subagent"] else "main",
                    "model_override": tool_input.get("model"), "input": tool_input,
                }
    return list(spawns.values())


def share(part: float, whole: float) -> float | None:
    return round(part / whole, 4) if whole else None


def aggregate_usage(transcripts: list[dict], window: Window, prices: PriceTable) -> dict:
    calls = dedupe_calls(transcripts, window)
    tool_calls = {}
    for transcript in transcripts:
        for tool_id, (name, tool_input, timestamp) in transcript["tools"].items():
            if tool_id in tool_calls or not window.contains(timestamp):
                continue
            tool_calls[tool_id] = (name, transcript["is_subagent"])

    total = zero()
    by_agent: dict = {}
    by_model: dict = {}
    by_day: dict = {}
    agent_models: dict = collections.defaultdict(collections.Counter)
    model_by_agent_by_day: dict = {}
    by_project: dict = {}
    by_session: dict = {}
    cost_by_agent: collections.Counter = collections.Counter()
    cost_by_model: collections.Counter = collections.Counter()
    first = last = None
    for record in calls.values():
        usage = record["u"]
        add(total, usage)
        add(by_agent.setdefault(record["agent"], zero()), usage)
        add(by_model.setdefault(record["model"], zero()), usage)
        agent_models[record["agent"]][record["model"]] += 1
        project = by_project.setdefault(record["project"], {"all": zero(), "sessions": set()})
        add(project["all"], usage)
        project["sessions"].add(record["session"])
        session = by_session.setdefault(
            (record["project"], record["session"]), {"all": zero(), "main": zero(), "sub": zero()})
        add(session["all"], usage)
        add(session["sub" if record["sub"] else "main"], usage)
        if prices:
            cost = prices.cost(record["model"], usage)
            cost_by_agent[record["agent"]] += cost
            cost_by_model[record["model"]] += cost
        if record["ts"]:
            first = record["ts"] if first is None or record["ts"] < first else first
            last = record["ts"] if last is None or record["ts"] > last else last
            day = window.day_of(record["ts"])
            entry = by_day.setdefault(day, {"main": zero(), "subagents": zero()})
            add(entry["subagents" if record["sub"] else "main"], usage)
            day_models = model_by_agent_by_day.setdefault(day, {}).setdefault(record["agent"], collections.Counter())
            day_models[record["model"]] += 1

    total_weighted = sum(weighted(d) for d in by_agent.values())
    total_output = total["output"]
    total_input = sum(total[k] for k in TOKEN_KINDS if k != "output")
    run_counts = collections.Counter(t["agent"] for t in transcripts if t["is_subagent"])
    agents = {}
    for name, usage in sorted(by_agent.items(), key=lambda item: -weighted(item[1])):
        entry = {
            **usage, "weighted_cost_units": round(weighted(usage)),
            "transcripts": run_counts.get(name, 0) if name != "main" else sum(1 for t in transcripts if not t["is_subagent"]),
            "models": dict(agent_models[name].most_common()),
            "share_output": share(usage["output"], total_output),
            "share_input_plus_cache": share(sum(usage[k] for k in TOKEN_KINDS if k != "output"), total_input),
            "share_weighted_cost": share(weighted(usage), total_weighted),
        }
        if prices:
            entry["cost_usd"] = round(cost_by_agent[name], 6)
        agents[name] = entry
    models = {}
    for name, usage in sorted(by_model.items(), key=lambda item: -weighted(item[1])):
        models[name] = {**usage, "total_tokens": sum(usage[k] for k in TOKEN_KINDS),
                        "weighted_cost_units": round(weighted(usage))}
        if prices:
            models[name]["cost_usd"] = round(cost_by_model[name], 6)

    spawns = [s for s in resolve_spawns(transcripts) if window.contains(s["ts"])]
    spawn_types = collections.Counter(s["type"] for s in spawns)
    tool_counts = {"main": collections.Counter(), "subagents": collections.Counter(), "all": collections.Counter()}
    for name, is_subagent in tool_calls.values():
        tool_counts["subagents" if is_subagent else "main"][name] += 1
        tool_counts["all"][name] += 1
    overrides = collections.Counter(f"{s['type']}:{s['model_override']}" for s in spawns if s["model_override"])

    projects = []
    for name, entry in sorted(by_project.items(), key=lambda item: -weighted(item[1]["all"]))[:15]:
        projects.append({"dir": name, "sessions": len(entry["sessions"]), **entry["all"],
                         "weighted_cost_units": round(weighted(entry["all"]))})
    sessions = []
    for (project, session), entry in sorted(by_session.items(), key=lambda item: -weighted(item[1]["all"]))[:10]:
        sessions.append({"project_dir": project, "session": session, **entry["all"],
                         "main_calls": entry["main"]["calls"], "subagent_calls": entry["sub"]["calls"],
                         "weighted_cost_units": round(weighted(entry["all"]))})
    result = {
        "date_range": {"first": first, "last": last, "since": window.since and window.since.isoformat(),
                       "until": window.until and window.until.isoformat(), "timezone_for_by_day": str(window.tz)},
        "totals": {
            "sessions": len(by_session), "api_calls": total["calls"], **{k: total[k] for k in TOKEN_KINDS},
            "input_plus_cache": total_input, "weighted_cost_units": round(total_weighted),
            "weighted_cost_units_note": "input=1, cache_creation=1.25, cache_read=0.1, output=5 (relative, model-agnostic)",
        },
        "by_agent": agents,
        "by_model": models,
        "by_day": {
            day: {"main_tokens": sum(e["main"][k] for k in TOKEN_KINDS),
                  "subagent_tokens": sum(e["subagents"][k] for k in TOKEN_KINDS),
                  "main_output": e["main"]["output"], "subagent_output": e["subagents"]["output"],
                  "main_calls": e["main"]["calls"], "subagent_calls": e["subagents"]["calls"]}
            for day, e in sorted(by_day.items())
        },
        "model_by_agent_by_day": {
            day: {agent: dict(counter.most_common()) for agent, counter in sorted(per_agent.items())}
            for day, per_agent in sorted(model_by_agent_by_day.items())
        },
        "by_project_top15": projects,
        "top10_sessions": sessions,
        "tool_usage_top20": [
            {"tool": name, "main": tool_counts["main"][name], "subagents": tool_counts["subagents"][name],
             "total": tool_counts["all"][name]}
            for name, _ in tool_counts["all"].most_common(20)
        ],
        "agent_spawns_by_subagent_type": dict(spawn_types.most_common()),
        "agent_spawns_without_subagent_type": sum(1 for s in spawns if not s["declared"]),
        "agent_spawns_by_caller": dict(collections.Counter(s["caller"] for s in spawns)),
        "agent_model_overrides": dict(overrides.most_common()),
    }
    if prices:
        result["totals"]["cost_usd"] = round(sum(cost_by_model.values()), 6)
        result["unpriced_models"] = sorted(prices.unpriced)
    return result


# ---------------------------------------------------------------------------
# Per-run statistics
# ---------------------------------------------------------------------------


def project_name(cwds: collections.Counter, project_dir: str) -> str:
    common = cwds.most_common(1)
    return home_relative(common[0][0]) if common else "/" + project_dir.lstrip("-").replace("-", "/")


def top_level_dir(path: str, cwds: collections.Counter) -> str:
    """The first directory of an edited file below the run's working directory."""
    common = cwds.most_common(1)
    base = common[0][0].rstrip("/") if common else ""
    if base and path.startswith(base + "/"):
        relative = path[len(base) + 1:]
        return relative.split("/")[0] if "/" in relative else "."
    return "(outside working directory)"


def build_runs(transcripts: list[dict], window: Window, classifier: CommandClassifier, prices: PriceTable,
               include_prompts: bool = True) -> list[dict]:
    """One record per subagent run that started inside the window."""
    spawn_inputs = {}
    for transcript in transcripts:
        for tool_id, (name, tool_input, _timestamp) in transcript["tools"].items():
            if name in SPAWN_TOOLS:
                spawn_inputs.setdefault(tool_id, tool_input)
    project_cwds: dict = collections.defaultdict(collections.Counter)
    for transcript in transcripts:
        project_cwds[transcript["project"]].update(transcript["cwds"])

    runs = []
    for transcript in transcripts:
        if not transcript["is_subagent"] or not transcript["timestamps"] or not transcript["calls"]:
            continue
        start, end = min(transcript["timestamps"]), max(transcript["timestamps"])
        if not window.contains(start):
            continue
        meta = transcript["meta"]
        calls = list(transcript["calls"].values())
        cost = sum(weighted(call["u"]) for call in calls)
        tool_counts = collections.Counter(name for name, _input, _ts in transcript["tools"].values())
        files: list[str] = []
        full = targeted = verification = bash = 0
        for name, tool_input, _timestamp in transcript["tools"].values():
            if name in EDIT_TOOLS:
                path = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path")
                if path and path not in files:
                    files.append(path)
            elif name == "Bash":
                command = tool_input.get("command") or ""
                bash += 1
                kind = classifier.classify(command)
                full += kind == "full"
                targeted += kind == "targeted"
                verification += classifier.is_verification(command)
        top_dirs = {top_level_dir(path, transcript["cwds"]) for path in files}
        spawn_input = spawn_inputs.get(meta.get("toolUseId"))
        handback = [i.get("message") for n, i, _ in transcript["tools"].values()
                    if n == "SubagentHandback" and isinstance(i.get("message"), str)]
        texts = transcript["texts"]
        report = handback[-1] if handback else (texts[-1] if texts else None)
        run = {
            "agent": transcript["agent"], "id": transcript["agent_id"], "session": transcript["session"],
            "project": project_name(project_cwds[transcript["project"]], transcript["project"]),
            "start": start, "end": end,
            "duration_min": round((parse_timestamp(end) - parse_timestamp(start)).total_seconds() / 60, 2),
            "description": meta.get("description"),
            "prompt_matched": spawn_input is not None,
            "parent_subagent_type_in_call": (spawn_input or {}).get("subagent_type"),
            "models": dict(collections.Counter(call["model"] for call in calls)),
            "api_calls": len(calls), "weighted_cost": round(cost),
            "output_tokens": sum(call["u"]["output"] for call in calls),
            "tool_counts": dict(tool_counts.most_common()),
            "files_edited": files[:40], "files_edited_total": len(files),
            "top_level_dirs_edited": sorted(top_dirs),
            "bash_calls": bash, "verification_bash_calls": verification,
            "full_gate_calls": full, "targeted_test_calls": targeted,
            "final_report": truncate(report, MAX_REPORT_CHARS),
            "final_report_source": "SubagentHandback" if handback else ("text" if texts else None),
            "finished_flag": meta.get("finished"),
        }
        if include_prompts:
            prompt = (spawn_input or {}).get("prompt")
            if isinstance(prompt, str) and len(prompt) > MAX_PROMPT_CHARS:
                prompt = prompt[:4500] + "…" + prompt[-1500:]
            run["prompt"] = prompt
        if prices:
            run["cost_usd"] = round(sum(prices.cost(call["model"], call["u"]) for call in calls), 6)
        runs.append(run)
    runs.sort(key=lambda run: run["start"])
    return runs


def run_stats(runs: list[dict], prices: PriceTable) -> dict:
    """Per-agent-type statistics over the runs; shares are of all subagent runs' weighted cost."""
    total_cost = sum(run["weighted_cost"] for run in runs)
    stats: dict = {}
    for agent in sorted({run["agent"] for run in runs}):
        group = [run for run in runs if run["agent"] == agent]
        models = collections.Counter()
        for run in group:
            models.update(run["models"])
        costs = [run["weighted_cost"] for run in group]
        entry = {
            "count": len(group),
            "api_calls": {"median": median([r["api_calls"] for r in group]),
                          "p90": percentile([r["api_calls"] for r in group], 0.9)},
            "weighted_cost": {"median": median(costs), "p90": percentile(costs, 0.9),
                              "mean": round(statistics.mean(costs)), "total": sum(costs),
                              "share_of_subagent_runs": share(sum(costs), total_cost)},
            "files_edited_median": median([r["files_edited_total"] for r in group]),
            "duration_min_median": median([r["duration_min"] for r in group]),
            "bash_calls": {"median": median([r["bash_calls"] for r in group]), "total": sum(r["bash_calls"] for r in group)},
            "verification_bash_calls": {"median": median([r["verification_bash_calls"] for r in group]),
                                        "p90": percentile([r["verification_bash_calls"] for r in group], 0.9),
                                        "total": sum(r["verification_bash_calls"] for r in group)},
            "full_gate_calls": {"median": median([r["full_gate_calls"] for r in group]),
                                "p90": percentile([r["full_gate_calls"] for r in group], 0.9),
                                "total": sum(r["full_gate_calls"] for r in group)},
            "targeted_test_calls": {"median": median([r["targeted_test_calls"] for r in group]),
                                    "total": sum(r["targeted_test_calls"] for r in group)},
            "models_by_api_calls": dict(models.most_common()),
            "runs_with_prompt_matched": sum(r["prompt_matched"] for r in group),
        }
        if prices:
            entry["cost_usd_total"] = round(sum(r.get("cost_usd", 0.0) for r in group), 6)
        stats[agent] = entry
    return stats


def headline(usage: dict, runs: list[dict], stats: dict, implementation_agents) -> dict:
    """The numbers docs/subagent-routing-cost-plan.md tracks."""
    implementation = [run for run in runs if run["agent"] in implementation_agents]
    counts = {agent: sum(1 for run in implementation if run["agent"] == agent) for agent in implementation_agents}
    spawns = usage["agent_spawns_by_subagent_type"]
    complex_runs = counts.get("worker-complex", 0)
    return {
        "worker_complex_share_of_weighted_cost": (usage["by_agent"].get("worker-complex") or {}).get("share_weighted_cost"),
        "implementation_agents": list(implementation_agents),
        "implementation_runs": counts,
        "worker_complex_share_of_implementation_runs": share(complex_runs, len(implementation)),
        "median_verification_bash_calls_per_implementation_run": median([r["verification_bash_calls"] for r in implementation]),
        "median_full_gate_calls_per_implementation_run": median([r["full_gate_calls"] for r in implementation]),
        "median_targeted_test_calls_per_implementation_run": median([r["targeted_test_calls"] for r in implementation]),
        "validator_runs": (stats.get("validator") or {}).get("count", 0),
        "general_purpose_spawns": spawns.get("general-purpose", 0),
        "unspecified_spawns": spawns.get(UNSPECIFIED, 0),
        "note": "WORKER_ENOUGH share needs the reviewed verdicts; see audit/README.md.",
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def write_jsonl(path: Path, rows) -> None:
    with open(path, "w") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_outputs(out: Path, usage: dict, runs: list[dict], stats: dict, head: dict,
                  review_agent: str | None, batches: int) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = [out / "usage.json", out / "runs.jsonl", out / "run_stats.json", out / "headline.json"]
    write_json(written[0], usage)
    write_jsonl(written[1], runs)
    write_json(written[2], stats)
    write_json(written[3], head)
    if review_agent and batches > 0:
        review = [{k: v for k, v in run.items() if k != "agent"} for run in runs if run["agent"] == review_agent]
        directory = out / "review"
        directory.mkdir(exist_ok=True)
        bounds = [round(len(review) * i / batches) for i in range(batches + 1)]
        for index in range(batches):
            path = directory / f"batch_{index + 1}.jsonl"
            write_jsonl(path, review[bounds[index]:bounds[index + 1]])
            written.append(path)
    return written


def format_summary(usage: dict, stats: dict, head: dict) -> str:
    lines = [
        f"calls {usage['totals']['api_calls']}  sessions {usage['totals']['sessions']}  "
        f"weighted cost {usage['totals']['weighted_cost_units']:,}",
        "",
        f"{'agent':<18}{'runs':>6}{'cost share':>12}{'cost/run':>14}{'verif med':>11}{'full med':>10}{'tgt med':>9}",
    ]
    for agent, entry in usage["by_agent"].items():
        stat = stats.get(agent)
        share_text = f"{entry['share_weighted_cost']:.1%}" if entry["share_weighted_cost"] is not None else "-"
        if stat:
            lines.append(f"{agent:<18}{stat['count']:>6}{share_text:>12}{stat['weighted_cost']['mean']:>14,}"
                         f"{stat['verification_bash_calls']['median']:>11}{stat['full_gate_calls']['median']:>10}"
                         f"{stat['targeted_test_calls']['median']:>9}")
        else:
            lines.append(f"{agent:<18}{'-':>6}{share_text:>12}")
    lines += ["", "headline"]
    lines += [f"  {key}: {value}" for key, value in head.items() if key != "note"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="usage-audit", description="Audit Claude Code transcripts for token usage, spawns, and verification effort.")
    parser.add_argument("--since", help="first local day to include, YYYY-MM-DD (default: no lower bound)")
    parser.add_argument("--until", help="last local day to include, inclusive, YYYY-MM-DD (default: no upper bound)")
    parser.add_argument("--out", help=f"output directory (default: {DEFAULT_OUT_ROOT}/<today>/)")
    parser.add_argument("--projects-dir", default=DEFAULT_PROJECTS_DIR,
                        help=f"Claude Code transcript directory (default: {DEFAULT_PROJECTS_DIR})")
    parser.add_argument("--tz", help="IANA time zone for day boundaries (default: the local zone)")
    parser.add_argument("--config", help="TOML file with [commands] regex lists and an optional [prices.<model>] table")
    parser.add_argument("--full-gate", action="append", default=[], metavar="REGEX",
                        help="regex for a full-gate command; repeat to replace the default list")
    parser.add_argument("--targeted", action="append", default=[], metavar="REGEX",
                        help="regex marking a test-runner command as targeted; repeat to replace the default list")
    parser.add_argument("--implementation-agents", default=",".join(DEFAULT_IMPLEMENTATION_AGENTS),
                        help="comma-separated agent types counted as implementation runs")
    parser.add_argument("--review-agent", default="worker-complex",
                        help="agent type whose runs are split into review batches (default: worker-complex; empty for none)")
    parser.add_argument("--batches", type=int, default=4, help="number of review batch files (default: 4)")
    parser.add_argument("--no-prompts", action="store_true", help="leave the delegation prompts out of runs.jsonl")
    parser.add_argument("--quiet", action="store_true", help="do not print the summary")
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    since, until = parse_day(args.since, "--since"), parse_day(args.until, "--until")
    if since and until and since > until:
        raise AuditError("--since is after --until")
    if args.batches < 0:
        raise AuditError("--batches must not be negative")
    window = Window(since, until, resolve_timezone(args.tz))
    config = load_config(args.config)
    classifier = classifier_from(config, args.full_gate, args.targeted)
    prices = PriceTable(config.get("prices"))
    implementation = tuple(a.strip() for a in args.implementation_agents.split(",") if a.strip())
    if not implementation:
        raise AuditError("--implementation-agents names no agent type")
    today = datetime.datetime.now(window.tz).strftime("%Y-%m-%d")
    out = Path(os.path.expanduser(args.out)) if args.out else Path(os.path.expanduser(DEFAULT_OUT_ROOT)) / today

    transcripts = load_transcripts(Path(os.path.expanduser(args.projects_dir)), window.modified_floor())
    usage = aggregate_usage(transcripts, window, prices)
    runs = build_runs(transcripts, window, classifier, prices, include_prompts=not args.no_prompts)
    stats = run_stats(runs, prices)
    head = headline(usage, runs, stats, implementation)
    written = write_outputs(out, usage, runs, stats, head, args.review_agent or None, args.batches)
    if not args.quiet:
        print(format_summary(usage, stats, head))
        print()
    print(f"wrote {len(written)} files to {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except AuditError as error:
        print(f"usage-audit: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
