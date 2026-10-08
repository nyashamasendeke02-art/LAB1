"""Knowledge plane (K1): a knowledge graph over one or more lab ledgers.

The graph is *derived* from the ledgers (never stored separately, so it cannot drift from them)
and rebuilt when a ledger head changes. Nodes are knowledge-bearing records (problems, claims,
questions, hypotheses, designs, protocols, results, conclusions, failures, future questions,
deliveries); edges are their ``refs``. Retrieval is Okapi BM25 over each node's text. Other labs
are opened read-only.

Used by the controller to give research stages the lab's prior knowledge, to verify claims that
cite lab records (``lab:<lab>/<record id>``), and to turn open questions into new projects.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .store import Record, Store

INDEXED_KINDS = ("problem", "background", "claim", "question", "hypothesis", "design",
                 "protocol", "result", "conclusion", "failure", "future_question", "delivery",
                 "observation")
# Failures that are operational noise (crashes, usage limits) rather than knowledge.
NOISE_FAILURES = {"stage_error"}
SOURCE = re.compile(r"^lab:([A-Za-z0-9_.\-]+)/([A-Z]+-\d+)$")
_TOKEN = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
STOPWORDS = frozenset("""a an and are as at be by can could does for from has have how if in into
is it its may not of on or that the their then there these this to under was were what when
whether which while will with within without would than""".split())


def tokens(text: str) -> list[str]:
    """Word tokens; a compound ("heavy-ball", "g1-6", "src.safety") yields itself and its
    parts, so both "heavy ball" and the exact compound match."""
    out = []
    for t in _TOKEN.findall(text.lower()):
        parts = re.split(r"[._-]", t)
        for w in ([t] if len(parts) > 1 else []) + parts:
            if w not in STOPWORDS and len(w) > 1:
                out.append(w)
    return out


def _s(v) -> str:
    if isinstance(v, (list, tuple)):
        return "; ".join(_s(x) for x in v)
    if isinstance(v, dict):
        return "; ".join(f"{k}: {_s(x)}" for k, x in v.items())
    return "" if v is None else str(v)


def node_text(kind: str, d: dict) -> str:
    """The searchable text of a record (what a researcher would want to find it by)."""
    if kind == "problem":
        return " ".join(_s(d.get(k)) for k in ("problem_statement", "scope", "success_notion"))
    if kind == "background":
        return f"methods: {_s(d.get('known_methods'))} gaps: {_s(d.get('gaps'))}"
    if kind == "claim":
        return f"{_s(d.get('statement'))} sources: {_s(d.get('sources'))}"
    if kind == "question":
        return f"{_s(d.get('question'))} {_s(d.get('rationale'))}"
    if kind == "hypothesis":
        return " ".join(_s(d.get(k)) for k in ("statement", "prediction", "falsification"))
    if kind == "design":
        opts = "; ".join(f"{o.get('name')}: {o.get('description', '')}"
                         for o in d.get("options", []) if isinstance(o, dict))
        return f"chosen {_s(d.get('chosen'))}: {_s(d.get('rationale'))} options: {opts}"
    if kind == "protocol":
        p = d.get("protocol") or {}
        conds = ", ".join(f"{c.get('name')} ({c.get('role')})" for c in p.get("conditions", []))
        return (f"{_s(p.get('title'))} [{_s(p.get('kind'))}, {_s(d.get('status'))}] "
                f"conditions: {conds} metrics: {_s(p.get('metrics'))}")
    if kind == "result":
        dec = d.get("decision") or {}
        return (f"outcome {_s(d.get('outcome'))}: {dec.get('treatment')} vs {dec.get('control')} "
                f"on {dec.get('metric')}, effect {dec.get('effect')}, CI [{dec.get('ci_low')}, "
                f"{dec.get('ci_high')}], n={dec.get('n_pairs') or dec.get('n_treatment')}")
    if kind == "conclusion":
        dec = d.get("decision") or {}
        tested = (f" tested {dec.get('treatment')} vs {dec.get('control')} on {dec.get('metric')}: "
                  f"effect {dec.get('effect')}, CI [{dec.get('ci_low')}, {dec.get('ci_high')}]"
                  if dec else "")
        return (f"{_s(d.get('statement'))} outcome {_s(d.get('outcome'))} "
                f"({_s(d.get('confidence'))}){tested} caveats: {_s(d.get('caveats'))}")
    if kind == "failure":
        return f"failure {_s(d.get('category'))} at {_s(d.get('state'))}: {_s(d.get('summary'))}"
    if kind == "future_question":
        return f"{_s(d.get('question'))} {_s(d.get('rationale'))}"
    if kind == "observation":
        return (f"observation from {_s(d.get('kind'))} failure {_s(d.get('category'))} "
                f"({_s(d.get('specialty'))}): {_s(d.get('summary'))} "
                f"verdict {_s(d.get('verdict'))}: {_s(d.get('triage_rationale'))}")
    if kind == "delivery":
        return (f"delivered: {_s(d.get('spec'))} acceptance: {_s(d.get('acceptance_criteria'))} "
                f"refs: {_s(d.get('mandate_refs'))}")
    return _s(d)


@dataclass
class Node:
    id: str            # "<lab>:<record id>"
    lab: str
    record_id: str
    kind: str
    project: str | None
    label: str | None   # evidence label where the record has one
    status: str | None  # outcome / status / category
    text: str
    created_at: str
    data: dict = field(repr=False, default_factory=dict)

    def brief(self, chars: int = 600) -> dict:
        return {"id": self.id, "source": f"lab:{self.lab}/{self.record_id}", "kind": self.kind,
                "project": self.project, "label": self.label, "status": self.status,
                "text": self.text[:chars], "created_at": self.created_at}


class KnowledgeGraph:
    """Nodes, typed edges and a BM25 index over the knowledge records of several ledgers."""

    def __init__(self, sources: dict[str, Store]):
        self.sources = sources
        self.nodes: dict[str, Node] = {}
        self.edges: list[tuple[str, str, str]] = []   # (src, relation, dst)
        self._build()

    # ------------------------------------------------------------------ build
    @staticmethod
    def _status(kind: str, d: dict) -> str | None:
        if kind == "failure":
            return d.get("category")
        return d.get("outcome") or d.get("status")

    def _build(self) -> None:
        for lab, store in self.sources.items():
            recs: list[Record] = []
            for kind in INDEXED_KINDS:
                for rec in store.query(kind):
                    if kind == "failure" and rec.data.get("category") in NOISE_FAILURES:
                        continue
                    recs.append(rec)
            for rec in recs:
                nid = f"{lab}:{rec.id}"
                self.nodes[nid] = Node(nid, lab, rec.id, rec.kind, rec.data.get("project"),
                                       rec.data.get("label"), self._status(rec.kind, rec.data),
                                       node_text(rec.kind, rec.data), rec.created_at, rec.data)
            for rec in recs:
                for rel, val in (rec.data.get("refs") or {}).items():
                    for ref in ([val] if isinstance(val, str) else val
                                if isinstance(val, list) else []):
                        dst = f"{lab}:{ref}"
                        if isinstance(ref, str) and dst in self.nodes:
                            self.edges.append((f"{lab}:{rec.id}", rel, dst))
        # BM25 index
        self._docs = {nid: Counter(tokens(n.text)) for nid, n in self.nodes.items()}
        self._len = {nid: sum(c.values()) for nid, c in self._docs.items()}
        self._avg = (sum(self._len.values()) / len(self._len)) if self._len else 0.0
        df: Counter = Counter()
        for c in self._docs.values():
            df.update(c.keys())
        n = len(self._docs)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    # ------------------------------------------------------------------ queries
    def search(self, query: str, k: int = 10, kinds: tuple[str, ...] | None = None,
               exclude_project: tuple[str, str] | None = None,
               k1: float = 1.2, b: float = 0.75) -> list[tuple[float, Node]]:
        """Top-k nodes by BM25. ``exclude_project`` = (lab, project id) to leave out."""
        q = set(tokens(query))
        scored = []
        for nid, tf in self._docs.items():
            node = self.nodes[nid]
            if kinds and node.kind not in kinds:
                continue
            if exclude_project and (node.lab, node.project) == exclude_project:
                continue
            score = 0.0
            for t in q & tf.keys():
                f = tf[t]
                score += self._idf[t] * f * (k1 + 1) / (
                    f + k1 * (1 - b + b * self._len[nid] / (self._avg or 1)))
            if score > 0:
                scored.append((score, node))
        scored.sort(key=lambda sn: (-sn[0], sn[1].id))
        return scored[:k]

    def neighbours(self, node_id: str) -> dict:
        return {"out": [(r, d) for s, r, d in self.edges if s == node_id],
                "in": [(s, r) for s, r, d in self.edges if d == node_id]}

    def resolve_source(self, source: str) -> Node | None:
        """The node a ``lab:<lab>/<record id>`` source names, if it exists."""
        m = SOURCE.match(source.strip())
        return self.nodes.get(f"{m.group(1)}:{m.group(2)}") if m else None

    def open_questions(self) -> list[Node]:
        qs = [n for n in self.nodes.values() if n.kind == "future_question" and n.status == "open"]

        def prio(n: Node) -> int:
            try:
                return int(n.data.get("priority", 99))
            except (TypeError, ValueError):
                return 99
        qs.sort(key=lambda n: n.created_at, reverse=True)  # newest first ...
        return sorted(qs, key=prio)                         # ... within each priority (stable)

    def stats(self) -> dict:
        return {"labs": sorted(self.sources), "nodes": len(self.nodes), "edges": len(self.edges),
                "by_kind": dict(sorted(Counter(n.kind for n in self.nodes.values()).items())),
                "by_lab": dict(sorted(Counter(n.lab for n in self.nodes.values()).items())),
                "open_questions": len(self.open_questions())}


class Knowledge:
    """The knowledge plane of one lab: its own ledger plus read-only included labs, with the
    graph cached per combination of ledger heads."""

    def __init__(self, lab_name: str, store: Store, lab_root: Path, cfg: dict):
        self.lab_name = lab_name
        self.cfg = cfg.get("knowledge", {}) or {}
        self.sources: dict[str, Store] = {lab_name: store}
        self.problems: list[str] = []
        for rel in self.cfg.get("include_labs", []) or []:
            other = (lab_root / rel).resolve()
            name = other.name
            if name in self.sources:
                self.problems.append(f"include_labs: duplicate lab name {name!r}")
                continue
            try:
                self.sources[name] = Store.open_readonly(other / ".autolab" / "lab.db")
            except Exception as exc:  # missing lab: keep working with what exists
                self.problems.append(f"include_labs {rel!r}: {exc}")
        self._cache: tuple[tuple, KnowledgeGraph] | None = None

    @property
    def context_items(self) -> int:
        return int(self.cfg.get("context_items", 8))

    def graph(self) -> KnowledgeGraph:
        key = tuple((n, s.head()) for n, s in sorted(self.sources.items()))
        if self._cache is None or self._cache[0] != key:
            self._cache = (key, KnowledgeGraph(self.sources))
        return self._cache[1]

    def context_for(self, project_id: str, query: str) -> dict | None:
        """Prior knowledge for a research stage: the most relevant records of OTHER projects
        (this lab and included labs), each citable as ``lab:<lab>/<id>``."""
        g = self.graph()
        hits = g.search(query, k=self.context_items, exclude_project=(self.lab_name, project_id))
        if not hits:
            return None
        # Graph expansion: a hit on any record of an earlier research line also brings that
        # line's conclusions (what came of it), which lexical matching alone can miss.
        seen = {n.id for _, n in hits}
        lines = list(dict.fromkeys((n.lab, n.project) for _, n in hits if n.project))
        for node in sorted(g.nodes.values(), key=lambda n: n.id):
            if (node.kind == "conclusion" and (node.lab, node.project) in lines
                    and node.id not in seen):
                hits.append((0.0, node))
                seen.add(node.id)
        return {
            "note": ("Prior knowledge from this lab's ledger and included labs, ranked by "
                     "relevance to this project. Each item is a recorded artifact: cite it as "
                     "SOURCE_CLAIM with source 'lab:<lab>/<id>' (the 'source' field). Its label "
                     "and status say how strong it is; negative and failed results are knowledge "
                     "too. Do not treat another project's result as this project's data."),
            "items": [n.brief() for _, n in hits],
        }

    def verify_sources(self, sources: list[str]) -> bool:
        """True if every source is a lab record that exists in the graph."""
        g = self.graph()
        return bool(sources) and all(g.resolve_source(s) is not None for s in sources)

    def close(self) -> None:
        for name, store in self.sources.items():
            if name != self.lab_name:
                store.close()
