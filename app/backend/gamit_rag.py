"""gamit_rag — local RAG retrieval over the official GAMIT/GLOBK manuals (gg/help/*.hlp).

Chunk the 135 .hlp files (~700KB, too large to stuff into the system prompt) and retrieve them
on demand with **pure-Python BM25** (zero external dependencies, no embedding model, no network;
Docker-friendly and in keeping with the "model-agnostic" spirit). Through the gamit_help(query)
tool the agent looks up a command's options/usage just-in-time, instead of memorising the entire
manual into its context.

Design trade-off: no vector embeddings (those need a model/GPU/API); BM25 is good enough for the
term-dense queries typical here ("command name + option keywords") and is fully self-contained.
The index is built on first call and cached in memory.
"""
import re
import math
from collections import Counter
from functools import lru_cache
from pathlib import Path

import os

GG = os.environ.get("GG_DIR", str(Path.home() / "gg"))
HELP_DIR = Path(GG) / "help"
COM_DIR = Path(GG) / "com"      # sh_* user-level shell commands; their docs live in the in-script comments/USAGE

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_.]+")
_CHUNK_CHARS = 1100   # target characters per chunk (greedily packed by paragraph)


def _tokenize(s):
    return [w.lower() for w in _WORD.findall(s)]


def _chunk_file(path):
    """Chunk one .hlp file: split into paragraphs at blank lines, greedily pack to ~_CHUNK_CHARS;
    each chunk carries the command name (the file stem)."""
    cmd = path.stem
    text = path.read_text(errors="replace")
    # a paragraph = a block of consecutive non-blank lines
    paras, cur = [], []
    for ln in text.splitlines():
        if ln.strip():
            cur.append(ln)
        elif cur:
            paras.append("\n".join(cur)); cur = []
    if cur:
        paras.append("\n".join(cur))

    chunks, buf = [], ""
    for p in paras:
        if buf and len(buf) + len(p) > _CHUNK_CHARS:
            chunks.append(buf); buf = p
        else:
            buf = (buf + "\n\n" + p) if buf else p
    if buf:
        chunks.append(buf)
    return [(cmd, c) for c in chunks]


class _BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.docs = docs                       # [(cmd, text)]  -- list of (command, text)
        self.k1, self.b = k1, b
        self.tok = [_tokenize(t) for _, t in docs]
        self.tf = [Counter(t) for t in self.tok]
        self.len = [len(t) for t in self.tok]
        self.N = len(docs)
        self.avgdl = (sum(self.len) / self.N) if self.N else 0.0
        df = Counter()
        for toks in self.tok:
            df.update(set(toks))
        self.idf = {w: math.log(1 + (self.N - d + 0.5) / (d + 0.5)) for w, d in df.items()}

    def search(self, query, k=5, restrict_cmd=None):
        q = _tokenize(query)
        # boost direct command-name hits (users often search by command)
        cmd_terms = {t for t in q}
        out = []
        for i, (cmd, text) in enumerate(self.docs):
            if restrict_cmd and cmd.lower() != restrict_cmd.lower():
                continue
            s = 0.0
            for w in q:
                f = self.tf[i].get(w, 0)
                if f:
                    idf = self.idf.get(w, 0.0)
                    s += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / (self.avgdl or 1)))
            if cmd.lower() in cmd_terms:        # the command name was mentioned directly in the query -> boost
                s += 5.0
            if s > 0:
                out.append((s, i))
        out.sort(reverse=True)
        return [{"command": self.docs[i][0], "score": round(sc, 3), "text": self.docs[i][1]}
                for sc, i in out[:k]]


def _chunk_com_script(path):
    """Extract user-level documentation from an sh_* script: the header comments (description)
    + the USAGE/echo block. The script is code, so take only the documentation parts."""
    cmd = path.stem
    try:
        lines = path.read_text(errors="replace").splitlines()
    except Exception:
        return []
    desc = []
    for ln in lines[1:]:                      # skip the shebang
        st = ln.lstrip()
        if st.startswith("#"):
            t = st.lstrip("#").rstrip()
            if t and not set(t) <= {"-", "=", "*"}:   # skip separator lines
                desc.append(t)
        elif st == "":
            continue
        else:
            break
    # USAGE: an echo containing "usage", or an echo line with <args> / -flag
    usage = []
    for ln in lines:
        if re.search(r"echo", ln) and (re.search(r"[Uu][Ss][Aa][Gg][Ee]", ln)
                                       or "<" in ln or re.search(r"\s-\w", ln)):
            u = re.sub(r'^\s*echo\s*-?n?\s*', "", ln).strip().strip('"').strip("'")
            if u:
                usage.append(u)
    parts = []
    if desc:
        parts.append("DESCRIPTION:\n" + "\n".join(desc[:50]))
    if usage:
        parts.append("USAGE:\n" + "\n".join(usage[:50]))
    text = "\n\n".join(parts)
    return [(cmd, text)] if text.strip() else []


@lru_cache(maxsize=1)
def _index():
    docs = []
    if HELP_DIR.is_dir():
        for p in sorted(HELP_DIR.glob("*.hlp")):
            docs.extend(_chunk_file(p))
    if COM_DIR.is_dir():
        for p in sorted(COM_DIR.glob("sh_*")):
            if p.is_file():
                docs.extend(_chunk_com_script(p))
    return _BM25(docs) if docs else None


def gamit_help(query, k=5, command=None, max_chars=1400):
    """Search the GAMIT/GLOBK manuals. query: natural language/keywords; command: restrict to a
    command (e.g. 'autcln'); -> {n_hits, commands_available?, hits:[{command,score,text}]}."""
    idx = _index()
    if idx is None:
        return {"error": f"GAMIT help directory not found: {HELP_DIR}", "n_hits": 0}
    if not (query or command):
        return {"error": "query or command is required", "n_hits": 0}
    q = query or command
    hits = idx.search(q, k=k, restrict_cmd=command)
    for h in hits:
        if len(h["text"]) > max_chars:
            h["text"] = h["text"][:max_chars] + f"\n...(truncated, {len(h['text'])} characters total; specify command='{h['command']}' to see all)"
    return {"query": q, "command": command, "n_hits": len(hits), "hits": hits}


def list_commands():
    """List the commands that have a manual (the file stems)."""
    if not HELP_DIR.is_dir():
        return []
    return sorted(p.stem for p in HELP_DIR.glob("*.hlp"))
