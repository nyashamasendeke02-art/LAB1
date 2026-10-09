"""D67: terminal UI (`autolab tui`), driven headlessly with Textual's pilot."""

import asyncio

import pytest

textual = pytest.importorskip("textual")

from textual.widgets import DataTable, Input, TabbedContent  # noqa: E402

from autolab.gates import Gates  # noqa: E402
from autolab.tui import DetailScreen, LabTUI  # noqa: E402

from scenario import make  # noqa: E402


@pytest.fixture
def lab_with_work(tmp_path):
    lab, ctl = make(tmp_path)
    pid = ctl.new_project("Investigate whether treat can produce higher score")
    assert ctl.run(pid)[-1].after == "COMPLETE"
    apr = Gates(lab.store).request("review:safety", "ENG-0001@abc", "safety review of the kernel")
    return lab, pid, apr.id


def test_tui_shows_the_lab_and_navigates(lab_with_work):
    lab, pid, apr = lab_with_work

    async def scenario():
        app = LabTUI(lab.root, interval=60)
        async with app.run_test(size=(160, 48)) as pilot:
            projects = app.query_one("#projects", DataTable)
            assert projects.row_count == 1
            assert app.query_one("#approvals-table", DataTable).row_count == 1
            assert app.query_one("#agents-table", DataTable).row_count >= 3
            assert app.query_one("#activity-table", DataTable).row_count > 10
            for key, tab in (("2", "approvals"), ("3", "agents"), ("5", "activity"), ("6", "queue"),
                             ("1", "overview")):
                await pilot.press(key)
                assert app.query_one(TabbedContent).active == tab
            projects.focus()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, DetailScreen)
            body = str(app.screen._body)
            assert "Conclusion" in body and "Recent agent calls" in body
            await pilot.press("escape")
            await pilot.press("slash")
            assert app.query_one(TabbedContent).active == "knowledge"
            search = app.query_one("#search", Input)
            search.value = "treat score"
            await pilot.press("enter")
            await pilot.pause()
            assert app.query_one("#knowledge-table", DataTable).row_count > 0
    asyncio.run(scenario())


def test_tui_decisions_need_a_note_and_are_recorded(lab_with_work):
    lab, pid, apr = lab_with_work

    async def scenario():
        app = LabTUI(lab.root, interval=60)
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.press("2")
            app._decide(True)  # no note: refused
            await pilot.pause()
            assert lab.store.get(apr).data["status"] == "pending"
            app.query_one("#note", Input).value = "read the kernel diff and ran the tests"
            await pilot.click("#approve")
            await pilot.pause()
            rec = lab.store.get(apr).data
            assert rec["status"] == "approved" and rec["decided_by"] == "human"
            assert app.query_one("#approvals-table", DataTable).row_count == 0
    asyncio.run(scenario())


def test_tui_refuses_decisions_during_an_agent_call(lab_with_work):
    lab, pid, apr = lab_with_work
    lab.store.append_event("controller", "task.dispatched", "TASK-9999",
                           {"role": "engineer", "stage": "build", "project": pid})

    async def scenario():
        app = LabTUI(lab.root, interval=60)
        async with app.run_test(size=(160, 48)) as pilot:
            await pilot.press("2")
            app.query_one("#note", Input).value = "checked"
            app._decide(True)
            await pilot.pause()
            assert lab.store.get(apr).data["status"] == "pending"
    asyncio.run(scenario())
