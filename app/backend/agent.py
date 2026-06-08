"""GamitAgent — a DeepSeek-driven GAMIT ReAct agent (orchestration + self-correction).

A ReAct agent with harness robustness hardened per the probe findings:
- multi-level fallback parsing of Thought/Action/Args;
- loop guard: abort on repeated identical calls + a near-limit deadline + nudge to finish
  on failure/repetition (the probe showed this is the key to convergence on class D);
- system prompt = full references knowledge base + tool descriptions + GAMIT hard-stop
  discipline (read the fatal first, never trust a stale summary).

run_stream() is a generator that yields events step by step for the server to relay over SSE.
"""
import re
import json
import ast

from engine import LLMEngine
from knowledge import full_knowledge
from tools.registry import GamitToolkit


def parse_action(text):
    thought, action, args = "", "", {}
    m = re.search(r"Thought:\s*(.*?)(?=\nAction:|\Z)", text, re.DOTALL)
    if m:
        thought = m.group(1).strip()
    m = re.search(r"Action:\s*(\w+)", text)
    if m:
        action = m.group(1).strip()
    m = re.search(r"Args:\s*(\{.*\})", text, re.DOTALL)
    if m:
        raw = m.group(1).strip()
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()
        # take the first balanced brace block
        try:
            args = json.loads(raw)
        except Exception:
            jm = re.search(r"\{.*\}", raw, re.DOTALL)
            if jm:
                try:
                    args = json.loads(jm.group())
                except Exception:
                    try:
                        args = ast.literal_eval(jm.group())
                    except Exception:
                        args = {}
    return thought, action, args


SYSTEM_TMPL = """You are a GAMIT processing agent. You operate native GAMIT end to end to perform GNSS
estimation and quality control. You work in a "think -> call a tool -> read the observation" loop
until you produce a conclusion or trigger a hard stop.

## Available tools
{tools}

## Response format (strictly this every turn; output exactly one Action)
Thought: <reasoning>
Action: <tool name>
Args: <JSON>

## Workflow (init -> run -> diagnose -> self-correct -> report)
0. **If the project has no tables/ yet (the user only has a pile of RINEX) -> run init_project first**:
   it auto-generates the full set of control files (station.info, etc.) from the RINEX. Only proceed to
   run_sh_gamit once it returns ready=True; for non-IGS private-network sites, if missing_apr is non-empty,
   note that their a priori coordinates may need manual review.
1. First use list_project / read_file to understand the project (tables/, rinex/, existing day directories).
2. Run the solution with run_sh_gamit; **after an abnormal abort never trust sh_gamit_<doy>.summary
   (it holds the previous, stale value)** — you must first check_status / read GAMIT.fatal for the exit status.
3. If there is a fatal -> locate the root cause via the exact fingerprints in the errors.md knowledge base
   (failure-stage order: orbit -> MAKEXP antenna name -> MAKEX station.info -> MODEL); change only one
   localizable configuration item at a time, record "hypothesis -> change -> result", retry at most 3 times,
   and stop and report to a human if there is no improvement.
4. If there is no fatal -> parse_summary for QC (postfit nrms ~0.2 / WL >90% / NL >80% is acceptable).
5. Deeper quality checks: rinex_audit finds "legal but wrong" antennas (no error raised, yet they bias the
   height); multiday_std shows multi-day per-station scatter; use globk_frame for height drift / bimodality;
   if a solution is produced but with fewer stations than expected -> diagnose_drops finds silently dropped
   stations; before reporting you may run qc_report for a one-stop verdict.
6. Done or stuck -> finish with a structured report.

## Consult the manual (gamit_help) — look it up, don't make it up
- For command options / control-file fields / sh_* script usage not covered by the knowledge base,
  **call gamit_help(query=..., command=...) to consult the official manual before acting**;
  e.g. when a fatal involves an unfamiliar command, or you need to change a sestbl./autcln.cmd option
  but are unsure of its exact name and value.
- **Never invent command names, option names, or values from memory**; when unsure, always look it up first.
  gamit_help searches the full local .hlp + sh_* documentation.

## Hard-stop discipline
- Two consecutive changes with no QC improvement -> stop, finish with status need_human.
- An unclassifiable fatal -> first consult gamit_help for the relevant command; if still unclassifiable,
  report the original text back and finish with need_human.
- Once you have the exact fingerprint from the fatal/log and have classified/fixed it, **move on immediately;
  do not keep reading auxiliary files**.

## Domain knowledge base (authoritative; judge based on this)
{knowledge}
"""


class GamitAgent:
    def __init__(self, project_dir, engine: LLMEngine, max_rounds=20):
        self.project_dir = project_dir
        self.engine = engine
        self.max_rounds = max_rounds
        self.toolkit = GamitToolkit(project_dir)
        self.system = SYSTEM_TMPL.format(tools=self.toolkit.descriptions,
                                         knowledge=full_knowledge())

    # memory bounding: cap both the number of retained exchanges and the prompt size,
    # so a long ReAct loop cannot grow the context (and memory) without bound.
    _MAX_HISTORY = 40          # keep at most the last N (role, content) entries
    _MAX_CONVO_CHARS = 18000   # hard cap on the assembled prompt

    def _convo(self, instruction, history):
        if len(history) > self._MAX_HISTORY:
            history = history[-self._MAX_HISTORY:]
        s = f"Task: {instruction}\nProject directory: {self.project_dir} (browse with list_project/read_file)\n"
        for role, content in history:
            s += f"\n{role}: {content}"
        s += "\n\nGive the next step. Thought/Action/Args:"
        if len(s) > self._MAX_CONVO_CHARS:   # truncate old history, keep head + recent
            head = s[:2000]
            s = head + "\n...(earlier steps omitted)...\n" + s[-(self._MAX_CONVO_CHARS - 4000):]
        return s

    def run_stream(self, instruction):
        """Generator: yields event dicts step by step. type in thought/action/observation/final/error."""
        history = []
        last_fp = ""
        repeat = 0
        for rnd in range(1, self.max_rounds + 1):
            resp = self.engine.generate(system_prompt=self.system,
                                        user_message=self._convo(instruction, history),
                                        stop=["Observation:"], max_tokens=1400)
            raw = resp["text"]
            if raw.startswith("Error during API call"):
                yield {"type": "error", "round": rnd, "message": raw}
                return
            thought, action, args = parse_action(raw)
            yield {"type": "thought", "round": rnd, "thought": thought,
                   "action": action, "args": args}

            if not action:
                history.append(("assistant", raw))
                history.append(("user", "Observation: malformed output; use the Thought/Action/Args format and give exactly one Action."))
                continue

            if action == "finish":
                yield {"type": "final", "round": rnd, "report": args}
                return

            obs = self.toolkit.run(action, args)
            yield {"type": "observation", "round": rnd, "action": action,
                   "observation": obs[:4000]}

            # loop guard (probe-verified: key to convergence on class D)
            fp = f"{action}:{json.dumps(args, sort_keys=True, default=str)}"
            repeat = repeat + 1 if fp == last_fp else 0
            last_fp = fp
            nudge = ""
            if repeat >= 2:
                yield {"type": "observation", "round": rnd, "action": "_guard",
                       "observation": "System interrupt: same call repeated; forcing wrap-up."}
                obs += "\n\n[system] You have repeated the same call several times. finish now based on the evidence you have."
            elif obs.startswith("ERROR") or repeat == 1:
                nudge = ("\n\n[system] The same call repeated or the target does not exist. If you already have the "
                         "exact fatal fingerprint and have made the classification/QC judgement, finish now; do not keep "
                         "looking for auxiliary files.")
            if self.max_rounds - rnd <= 2:
                nudge += "\n\n[system] Very few rounds left; you must finish now with your current conclusion."

            history.append(("assistant", raw))
            history.append(("user", f"Observation: {obs}{nudge}"))

        yield {"type": "final", "round": self.max_rounds,
               "report": {"status": "need_human",
                          "summary": "Reached the maximum number of rounds without converging; manual intervention needed."}}

    def run(self, instruction):
        """Non-streaming: run to completion and return the event list (handy for tests)."""
        events = list(self.run_stream(instruction))
        final = next((e for e in reversed(events) if e["type"] in ("final", "error")), None)
        return {"events": events, "final": final,
                "engine": {"model": self.engine.model,
                           "calls": self.engine.total_calls,
                           "in_tokens": self.engine.total_in_tokens,
                           "out_tokens": self.engine.total_out_tokens}}
