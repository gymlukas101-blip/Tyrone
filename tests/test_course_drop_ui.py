"""'I dropped this class' in the real built UI (?demo, no Python): Homework → By class → ⋯ → I dropped this class,
the confirm that names the class and the counts, "Removed … Undo", Settings → Accounts → Hidden classes → Show
again, and Monkey's own confirm (injected with window.__monkeyEvents, as the drop_course tool sends it).

The demo class is made up (MKTG 777, "Principles of Pretend Marketing"). Set MONKEY_DROP_SHOTS=<folder> to also
save screenshots there (never into the repo)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.test_m4_avatar import DIST, _serve

SHOTS = os.environ.get("MONKEY_DROP_SHOTS")


@pytest.fixture(scope="module")
def browser():
    pytest.importorskip("playwright")
    from tools.automation_eval import browser_path

    if browser_path() is None or not DIST.is_file():
        pytest.skip("needs Chromium and a built UI (npm run build)")
    from playwright.sync_api import sync_playwright

    srv = _serve()
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=browser_path())
        # &drop: the demo's two to-dos for the made-up class; &svg: the panel is under test, not the 3D avatar
        yield b, f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&svg&drop"
        b.close()
    srv.shutdown()


_PAGES: list = []


@pytest.fixture(autouse=True)
def _close_pages():
    yield
    while _PAGES:
        try:
            _PAGES.pop().close()
        except Exception:  # noqa: BLE001 - already closed
            pass


def _open(browser, w=1280, h=900):
    b, url = browser
    p = b.new_page(viewport={"width": w, "height": h})
    _PAGES.append(p)
    p.set_default_timeout(30000)
    p.goto(url)
    p.wait_for_function("() => !!window.__monkeyEvents && !!window.__monkeyReady", timeout=20000)
    return p


def _shot(p, name):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        try:
            p.screenshot(path=str(Path(SHOTS) / f"{name}.png"), animations="disabled", caret="hide", timeout=20000)
        except Exception as exc:  # noqa: BLE001 - a screenshot never fails a test
            print(f"screenshot {name} failed: {exc}")


def _homework_by_class(p):
    p.click("#asgBtn")
    card = p.locator(".card.assign:not(.todo)")
    card.locator(".tabs button[data-tab=class]").click()
    p.wait_for_selector(".card.assign section.asg-course[data-key='code:mktg777']")
    return card


def _visible_courses(p):
    return p.eval_on_selector_all(".card.assign:not(.todo) section.asg-course",
                                  "els => els.filter(e => !e.closest('.m-ghost')).map(e => e.dataset.key)")


def test_drop_from_homework_names_class_and_counts_then_undo(browser):
    p = _open(browser)
    card = _homework_by_class(p)
    assert "code:mktg777" in _visible_courses(p) and "code:math222" in _visible_courses(p)
    group = card.locator("section.asg-course[data-key='code:mktg777']")
    more = group.locator("button.cd-more")
    assert more.get_attribute("aria-label") == "More for MKTG 777" and more.get_attribute("aria-haspopup") == "menu"
    more.click()
    item = p.locator(".cd-menu [role=menuitem]")
    item.wait_for()
    assert "I dropped this class" in item.inner_text()
    assert more.get_attribute("aria-expanded") == "true"
    _shot(p, "1-homework-action")
    item.click()
    dlg = p.locator("dialog.cd-dlg[open]")
    dlg.wait_for()
    p.wait_for_function("() => { const d = document.querySelector('dialog.cd-dlg'); return d && d.getAnimations({subtree: true}).every(a => a.playState !== 'running'); }")
    text = dlg.inner_text()
    assert "Dropped MKTG 777?" in text and "Principles of Pretend Marketing" in text
    counts = dlg.locator(".cd-count").all_inner_texts()
    assert [c.split()[0] for c in counts] == ["3", "2"]                 # 3 assignments (2 open + 1 done), 2 to-dos
    assert "Read ch 4 for MKTG 777" in text and "Outline the pretend product launch" in text
    assert "Nothing changes on Canvas" in text
    _shot(p, "2-confirm")
    dlg.locator("button.cd-hide").click()
    toast = p.locator(".toast", has_text="Removed 3 MKTG 777 assignments and 2 to-dos")
    toast.wait_for()
    p.wait_for_function("() => !document.querySelector(\".card.assign section.asg-course[data-key='code:mktg777']:not(.m-ghost *)\")")
    assert "code:mktg777" not in _visible_courses(p) and "code:math222" in _visible_courses(p)
    _shot(p, "3-removed-undo")
    # the other tabs and the To-do list don't show it either
    card.locator(".tabs button", has_text="All to do").click()
    assert card.locator("li.asg .course", has_text="MKTG 777").count() == 0
    p.click("#todoBtn")
    p.wait_for_selector(".card.todo .todo-list")
    assert p.locator(".card.todo li.todo-row", has_text="MKTG 777").count() == 0
    assert p.locator(".card.todo li.todo-row", has_text="pretend product launch").count() == 0
    # Undo brings everything back
    toast.locator("button", has_text="Undo").click()
    p.locator(".toast", has_text="MKTG 777 is back").wait_for()
    p.wait_for_function("() => [...document.querySelectorAll('.card.todo li.todo-row')].some(r => r.textContent.includes('MKTG 777'))")
    p.wait_for_function("() => [...document.querySelectorAll('.card.assign:not(.todo) li.asg .course')].some(c => c.textContent === 'MKTG 777')")


def test_keep_it_changes_nothing_and_escape_closes_menu(browser):
    p = _open(browser)
    card = _homework_by_class(p)
    more = card.locator("section.asg-course[data-key='code:mktg777'] button.cd-more")
    more.click()
    p.locator(".cd-menu").wait_for()
    p.keyboard.press("Escape")
    p.wait_for_function("() => !document.querySelector('.cd-menu:not([data-leaving])')")
    assert more.get_attribute("aria-expanded") == "false"
    p.mouse.move(5, 5)                              # off the button: its hover lift isn't "stable" for a re-click
    more.click()
    p.locator(".cd-menu [role=menuitem]").click()
    p.locator("dialog.cd-dlg[open]").wait_for()
    p.locator("dialog.cd-dlg button.cd-keep").click()
    p.wait_for_function("() => !document.querySelector('dialog.cd-dlg').open")
    assert "code:mktg777" in _visible_courses(p)
    assert p.locator(".toast", has_text="Removed").count() == 0


def test_settings_lists_hidden_class_and_show_again(browser):
    p = _open(browser)
    card = _homework_by_class(p)
    card.locator("section.asg-course[data-key='code:mktg777'] button.cd-more").click()
    p.locator(".cd-menu [role=menuitem]").click()
    p.locator("dialog.cd-dlg[open] button.cd-hide").click()
    p.locator(".toast", has_text="Removed 3 MKTG 777").wait_for()
    p.wait_for_function("() => !document.querySelector('dialog.cd-dlg').open")
    p.evaluate("() => window.__monkeyEvents([['open_settings', {section: 'accounts'}]])")
    row = p.locator("#settings .cd-hidden-list li[data-key='code:mktg777']")
    row.wait_for()
    row.scroll_into_view_if_needed()
    assert "MKTG 777" in row.inner_text() and "2 to-dos archived" in row.inner_text()
    p.wait_for_timeout(400)                         # let the section's entrance settle before the screenshot
    _shot(p, "4-settings-hidden-classes")
    row.locator("button.cd-show").click()
    p.locator(".toast", has_text="MKTG 777 is back").wait_for()
    p.wait_for_selector("#settings .cd-hidden .cd-none")
    # the Homework card behind Settings has the class again
    p.wait_for_function("() => [...document.querySelectorAll(\".card.assign section.asg-course\")].some(s => s.dataset.key === 'code:mktg777')")


def test_monkeys_confirm_from_the_brain_tool(browser):
    """The drop_course tool's event opens the same confirm; pressing Hide it hides the class and offers Undo."""
    p = _open(browser)
    _homework_by_class(p)
    # The event carries what Python's preview returns; this token was never issued by the (demo) API.
    p.evaluate("""() => window.__monkeyEvents([['course_drop_confirm', {ok: true, key: 'code:mktg777', name: 'MKTG 777',
        full: 'Principles of Pretend Marketing', assignments: 3, todos: [{id: 't6', text: 'Read ch 4 for MKTG 777'}],
        token: 'never-issued'}]])""")
    dlg = p.locator("dialog.cd-dlg[open]")
    dlg.wait_for()
    assert "Dropped MKTG 777?" in dlg.inner_text()
    dlg.locator("button.cd-hide").click()
    # a token Python never issued is refused: nothing is hidden, the owner is told
    p.locator(".toast", has_text="Confirm it again").wait_for()
    assert "code:mktg777" in _visible_courses(p)
    p.keyboard.press("Escape")
    # Monkey did it (after a yes by voice): the course_dropped event shows what went, with Undo
    p.evaluate("""() => window.__monkeyEvents([['course_dropped', {ok: true, action: 'dropped', key: 'code:mktg777',
        name: 'MKTG 777', assignments: 3, todos: [{id: 't6', text: 'Read ch 4 for MKTG 777'}, {id: 't7', text: 'x'}]}]])""")
    p.locator(".toast", has_text="Removed 3 MKTG 777 assignments and 2 to-dos").locator("button", has_text="Undo").wait_for()


def test_narrow_window_menu_and_confirm_fit(browser):
    p = _open(browser, 420, 760)
    card = _homework_by_class(p)
    card.locator("section.asg-course[data-key='code:mktg777'] button.cd-more").click()
    box = p.locator(".cd-menu").bounding_box()
    assert box and box["x"] >= 0 and box["x"] + box["width"] <= 420
    p.locator(".cd-menu [role=menuitem]").click()
    p.locator("dialog.cd-dlg[open]").wait_for()
    p.wait_for_function("() => document.querySelector('dialog.cd-dlg').getAnimations({subtree: true}).every(a => a.playState !== 'running')")
    d = p.locator("dialog.cd-dlg").bounding_box()
    assert d and d["x"] >= 0 and d["x"] + d["width"] <= 420
    hide = p.locator("dialog.cd-dlg button.cd-hide").bounding_box()
    assert hide and hide["y"] + hide["height"] <= 760
