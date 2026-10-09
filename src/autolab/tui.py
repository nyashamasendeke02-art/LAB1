"""Terminal UI for a lab (D67): `autolab tui LAB`.

Minimal but functional: the web dashboard's data layer (DashboardServer.offline) in a keyboard-
driven terminal app, so both interfaces always show the same data. Requires the optional extra
``textual`` (pip install autolab[tui]).

Screens: 1 Overview (projects), 2 Approvals (decide with a required note), 3 Agents
(scorecards), 4 Knowledge (search), 5 Activity (ledger), 6 Queue (log). Enter opens details.
The app refreshes itself when the ledger or the queue log changes. Writes go through the same
guarded path as the dashboard: refused while an agent call is in flight.
"""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (Button, DataTable, Footer, Header, Input, RichLog, Static,
                             TabbedContent, TabPane)

from .controller import Lab
from .web import DashboardServer

TABS = ("overview", "approvals", "agents", "knowledge", "activity", "queue")


def _short(text, n: int = 70) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _money(v) -> str:
    return "–" if v is None else f"${v:.3f}"


class DetailScreen(ModalScreen):
    """Read-only details of one project or record (Esc to close)."""

    BINDINGS = [Binding("escape", "app.pop_screen", "Close"), Binding("q", "app.pop_screen", "Close")]
    DEFAULT_CSS = """
    DetailScreen { align: center middle; }
    #detail { width: 92%; height: 90%; border: round $accent; background: $panel; padding: 1 2; }
    """

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title, self._body = title, body

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="detail"):
            yield Static(f"[b]{self._title}[/b]\n")
            yield Static(self._body, markup=False)


class LabTUI(App):
    TITLE = "Autolab"
    CSS = """
    DataTable { height: 1fr; }
    #approval-actions { height: auto; padding: 1 0 0 0; }
    #approval-actions Input { width: 1fr; }
    #summary { height: auto; padding: 0 1; color: $text-muted; }
    """
    BINDINGS = [
        Binding("1", "tab('overview')", "Overview"), Binding("2", "tab('approvals')", "Approvals"),
        Binding("3", "tab('agents')", "Agents"), Binding("4", "tab('knowledge')", "Knowledge"),
        Binding("5", "tab('activity')", "Activity"), Binding("6", "tab('queue')", "Queue"),
        Binding("r", "refresh", "Refresh"), Binding("slash", "search", "Search", key_display="/"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, lab_path: str | Path, run_log: str | Path | None = None,
                 interval: float = 2.0) -> None:
        super().__init__()
        self.data = DashboardServer.offline(Lab(lab_path), run_log)
        self.interval = interval
        self._fingerprint = None
        self._approval_ids: list[str] = []

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="summary")
        with TabbedContent(initial="overview"):
            with TabPane("1 Overview", id="overview"):
                yield DataTable(id="projects", cursor_type="row", zebra_stripes=True)
            with TabPane("2 Approvals", id="approvals"):
                yield DataTable(id="approvals-table", cursor_type="row", zebra_stripes=True)
                with Horizontal(id="approval-actions"):
                    yield Input(placeholder="Review note (required): what did you check?", id="note")
                    yield Button("Approve", id="approve", variant="success")
                    yield Button("Reject", id="reject", variant="error")
            with TabPane("3 Agents", id="agents"):
                yield DataTable(id="agents-table", cursor_type="row", zebra_stripes=True)
            with TabPane("4 Knowledge", id="knowledge"):
                with Vertical():
                    yield Input(placeholder="Search what the lab knows…", id="search")
                    yield DataTable(id="knowledge-table", cursor_type="row", zebra_stripes=True)
            with TabPane("5 Activity", id="activity"):
                yield DataTable(id="activity-table", zebra_stripes=True)
            with TabPane("6 Queue", id="queue"):
                yield RichLog(id="queue-log", wrap=True, markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#projects", DataTable).add_columns("Project", "Kind", "State", "Meaning", "Title", "Updated")
        self.query_one("#approvals-table", DataTable).add_columns("Approval", "Gate", "Project", "Summary")
        self.query_one("#agents-table", DataTable).add_columns(
            "Agent", "Model", "Calls", "Success", "Avg s", "Cost", "Tools (denied)", "Stages")
        self.query_one("#knowledge-table", DataTable).add_columns("Score", "Record", "Entity", "Status", "Text")
        self.query_one("#activity-table", DataTable).add_columns("#", "When", "Type", "Subject", "Detail")
        self.refresh_all()
        self.set_interval(self.interval, self._poll)

    # ------------------------------------------------------------------ data
    def _poll(self) -> None:
        fp = self.data._fingerprint()
        if fp != self._fingerprint:
            self.refresh_all()

    def refresh_all(self) -> None:
        self._fingerprint = self.data._fingerprint()
        o = self.data.overview()
        meta = self.data.meta()
        labels = meta.get("state_labels", {})
        c, u = o["counts"], o.get("usage") or {}
        self.sub_title = o["lab"]
        ledger = o["ledger"]
        self.query_one("#summary", Static).update(
            f"{c['active']} active · {c['approvals']} awaiting you · {c['agents_working']} agent(s) working · "
            f"{c['deliveries']} delivered · {c['halted']} halted · cost {_money(u.get('cost_usd'))} · "
            f"ledger {'verified' if ledger.get('ok') else 'FAILED'} ({ledger.get('events', '?')} events)")
        projects = self.query_one("#projects", DataTable)
        projects.clear()
        for p in self.data.projects():
            projects.add_row(p["id"], p["kind"], p["state"], labels.get(p["state"], ""),
                             _short(p["title"], 60), str(p["updated_at"])[:16], key=p["id"])
        approvals = self.query_one("#approvals-table", DataTable)
        approvals.clear()
        self._approval_ids = []
        for a in self.data.approvals():
            approvals.add_row(a["id"], a["gate"], a.get("project") or "", _short(a["summary"], 80), key=a["id"])
            self._approval_ids.append(a["id"])
        agents = self.query_one("#agents-table", DataTable)
        agents.clear()
        for a in self.data.agents():
            sc = a.get("scorecard") or {}
            if not (a["stages"] or a["calls"]):
                continue
            tools = "–" if sc.get("tool_calls") is None else f"{sc['tool_calls']} ({sc['tool_denied']})"
            agents.add_row(a["title"].split(" (")[0], a.get("model") or "default", str(a["calls"]),
                           "–" if sc.get("success_rate") is None else f"{round(100 * sc['success_rate'])}%",
                           "–" if sc.get("avg_wall_s") is None else str(sc["avg_wall_s"]),
                           _money(sc.get("cost_usd")), tools, str(len(a["stages"])), key=a["name"])
        activity = self.query_one("#activity-table", DataTable)
        activity.clear()
        for e in self.data.activity(200):
            activity.add_row(str(e["seq"]), str(e["ts"])[11:19], e["type"], e["subject"], _short(e["brief"], 60))
        log = self.query_one("#queue-log", RichLog)
        log.clear()
        q = o.get("queue") or {}
        log.write(f"queue log: {q.get('log') or 'none'} (running: {q.get('running')})")
        for line in q.get("lines", []):
            log.write(line)

    # ------------------------------------------------------------------ actions
    def action_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab

    def action_refresh(self) -> None:
        self.refresh_all()
        self.notify("Refreshed")

    def action_search(self) -> None:
        self.action_tab("knowledge")
        self.query_one("#search", Input).focus()

    @on(Input.Submitted, "#search")
    def run_search(self, event: Input.Submitted) -> None:
        table = self.query_one("#knowledge-table", DataTable)
        table.clear()
        try:
            hits = self.data.knowledge_search({"q": [event.value]})
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        for h in hits:
            table.add_row(f"{h['score']:.2f}", h["source"].replace("lab:", ""), h.get("entity") or h["kind"],
                          h.get("status") or "", _short(h["text"], 90), key=h["source"])
        if not hits:
            self.notify("Nothing matches (retrieval is lexical: try the words the records use)")

    @on(DataTable.RowSelected, "#projects")
    def open_project(self, event: DataTable.RowSelected) -> None:
        pid = str(event.row_key.value)
        p = self.data.project(pid)
        lines = [f"State: {p['state']}   Kind: {p['kind']}   Cycle: {p['cycle']}",
                 f"Objective: {p['objective']}"]
        if p.get("halt_reason"):
            lines.append(f"HALTED: {p['halt_reason']}")
        r = p.get("research")
        if r:
            if r.get("problem"):
                lines += ["", "Problem:", "  " + _short(r["problem"].get("problem_statement"), 400)]
            for q in r["questions"]:
                lines += ["", f"Question {q['id']}:", "  " + _short(q["question"], 400)]
            if r["hypotheses"]:
                lines.append("")
                lines += [f"{'*' if h['current'] else ' '} {h['id']} [{h['status']}] {_short(h['statement'], 160)}"
                          for h in r["hypotheses"]]
            claims = r["background"]["claims"]
            if claims:
                lines += ["", f"Claims: {len(claims)} ({sum(c['verified'] for c in claims)} verified)"]
            for res in r["results"]:
                d = res.get("decision") or {}
                lines.append(f"Result {res['id']}: {res['outcome']}  effect {d.get('effect')}  "
                             f"CI [{d.get('ci_low')}, {d.get('ci_high')}]")
            for c in r["conclusions"]:
                lines.append(f"Conclusion {c['id']}: {c['outcome']} ({c['confidence']})")
        if p.get("eng"):
            e = p["eng"]
            lines += ["", f"Engineering {e['id']}: {e['state']}  patches {e['patch_attempts']}  "
                          f"redesigns {e['redesigns']}  reviews {e['review_round']}"]
        lines += ["", "Recent agent calls:"]
        for t in p["tasks"][:15]:
            lines.append(f"  {t['id']}  {t['stage']:<24} {t.get('agent') or t['role']:<14} {t['status']}")
        self.push_screen(DetailScreen(f"{p['id']} · {_short(p['title'], 80)}", "\n".join(lines)))

    @on(DataTable.RowSelected, "#knowledge-table")
    def open_record(self, event: DataTable.RowSelected) -> None:
        n = self.data.knowledge_node({"id": [str(event.row_key.value)]})
        lines = [n["text"], ""]
        lines += [f"  {e['relation']} -> {e['source'].replace('lab:', '')}  ({e.get('entity') or e['kind']})" for e in n["out"]]
        lines += [f"  <- {e['relation']}  {e['source'].replace('lab:', '')}  ({e.get('entity') or e['kind']})" for e in n["in"]]
        self.push_screen(DetailScreen(f"{n['source'].replace('lab:', '')} · {n.get('entity') or n['kind']}", "\n".join(lines)))

    @on(DataTable.RowSelected, "#approvals-table")
    def open_approval(self, event: DataTable.RowSelected) -> None:
        a = self.data.approval(str(event.row_key.value))
        body = f"{a['summary']}\n\nFiles: {', '.join(a['files']) or '-'}\n\n{a['diff'][:20000] or '(no diff)'}"
        self.push_screen(DetailScreen(f"{a['id']} · {a['gate']}", body))

    @on(Button.Pressed, "#approve")
    def approve(self) -> None:
        self._decide(True)

    @on(Button.Pressed, "#reject")
    def reject(self) -> None:
        self._decide(False)

    def _decide(self, approved: bool) -> None:
        table = self.query_one("#approvals-table", DataTable)
        if not self._approval_ids:
            self.notify("Nothing awaiting a decision")
            return
        approval_id = self._approval_ids[min(table.cursor_row, len(self._approval_ids) - 1)]
        note = self.query_one("#note", Input).value
        try:
            rec = self.data.decide(approval_id, {"approved": approved, "note": note})
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        self.query_one("#note", Input).value = ""
        self.notify(f"{rec['id']}: {rec['status']} (recorded as the human's decision)")
        self.refresh_all()


def run(lab_path: str | Path) -> None:
    LabTUI(lab_path).run()
