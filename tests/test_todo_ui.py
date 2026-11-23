"""The To-do panel in the real built UI (?demo, no Python): quick add with a visible, correctable due date, check off
with Undo, delete with Undo, edit, sub-steps, tabs, sort, reminders, keyboard and accessibility.

Set MONKEY_TODO_SHOTS=<folder> to also save screenshots of the panel there (never into the repo)."""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

from tests.test_m4_avatar import DIST, _serve

AXE = Path(__file__).resolve().parents[1] / "ui" / "node_modules" / "axe-core" / "axe.min.js"
CASES = json.loads((Path(__file__).parent / "todo_due_cases.json").read_text(encoding="utf-8"))
SHOTS = os.environ.get("MONKEY_TODO_SHOTS")


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
        # The panel is under test, not the avatar: &svg skips the 3D render, which crawls in software-rendered
        # Chromium on a busy machine (the avatar tests cover the 3D path over HTTP).
        yield b, f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&svg"
        b.close()
    srv.shutdown()


_PAGES: list = []


@pytest.fixture(autouse=True)
def _close_pages():
    """A failed assertion must not leave a page (and its 3D avatar) running: software-rendered Chromium then
    starves the next test's page load."""
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


def _panel(p):
    p.click("#todoBtn")
    p.wait_for_selector(".card.todo .todo-list")
    return p.locator(".card.todo")


def _row(p, text):
    return p.locator(".card.todo li.todo-row", has_text=text)


def _shot(p, name):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        try:                 # the whole window, so the panel is seen in context; never fails a test
            p.screenshot(path=str(Path(SHOTS) / f"{name}.png"), animations="disabled", caret="hide", timeout=20000)
        except Exception as exc:  # noqa: BLE001
            print(f"screenshot {name} skipped: {exc}")


def test_parser_matches_the_python_one(browser):
    p = _open(browser)
    got = p.evaluate("""cases => { const now = new Date(2026, 10, 23, 10, 0);
        return cases.map(c => window.__monkeyTodoParse(c.in, now)); }""", CASES["cases"])
    p.close()
    want = [{k: c[k] for k in ("text", "due", "priority", "list")} for c in CASES["cases"]]
    bad = [(c["in"], g, w) for c, g, w in zip(CASES["cases"], got, want) if g != w]
    assert not bad, bad


def test_panel_shows_open_items_with_overdue_highlighted(browser):
    p = _open(browser)
    card = _panel(p)
    assert card.locator("li.todo-row").count() == 4                       # the 4 open demo items, not the done one
    over = _row(p, "Email Prof. Kim")
    assert "overdue" in (over.get_attribute("class") or "") and over.locator(".flag").inner_text() == "OVERDUE"
    assert card.locator(".tabs button", has_text="Overdue (1)").count() == 1
    assert card.locator(".tabs button", has_text="Done (1)").count() == 1
    assert "1/3 steps" in _row(p, "CS 400").inner_text()
    _shot(p, "todo-panel")
    p.close()


def test_quick_add_shows_the_parsed_date_and_lets_you_correct_it(browser):
    p = _open(browser)
    card = _panel(p)
    p.fill("#todoNew", "renew my passport tomorrow 5pm !high")
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    chip = card.locator(".todo-parsed-chip")
    assert chip.inner_text().startswith("📅 Tomorrow")
    assert card.locator(".todo-parsed .todo-date").input_value() == tomorrow
    assert card.locator(".todo-parsed .todo-time").input_value() == "17:00"
    assert card.locator(".todo-parsed .todo-prio").input_value() == "high"
    _shot(p, "todo-quick-add")
    card.locator(".todo-parsed .todo-time").fill("09:30")                  # the user corrects the time
    p.wait_for_function("() => document.querySelector('.todo-parsed-chip').textContent.includes('9:30')")
    p.press("#todoNew", "Enter")
    row = _row(p, "renew my passport")
    row.wait_for()
    assert row.locator(".tier").inner_text().lower() == "high"
    assert "Tomorrow" in row.locator(".asg-why").inner_text() and "9:30" in row.locator(".asg-why").inner_text()
    assert p.input_value("#todoNew") == "" and card.locator(".todo-parsed").is_hidden()
    assert p.evaluate("() => document.activeElement.id") == "todoNew"     # ready for the next one
    p.close()


def test_check_off_then_undo(browser):
    p = _open(browser)
    card = _panel(p)
    row = _row(p, "Pick up package").element_handle()
    row.query_selector(".cb").click()
    undo = p.locator(".toast", has_text="Done:").locator("button", has_text="Undo")
    undo.wait_for()
    p.wait_for_function("() => [...document.querySelectorAll('.card.todo .tabs button')].some(b => b.textContent === 'Done (2)')")
    assert _row(p, "Pick up package").count() == 0                       # moved off the Open tab
    undo.click()
    p.wait_for_function("() => [...document.querySelectorAll('.card.todo li.todo-row')].some(li => li.textContent.includes('Pick up package'))")
    assert card.locator(".tabs button", has_text="Done (1)").count() == 1
    p.close()


def test_delete_then_undo(browser):
    p = _open(browser)
    card = _panel(p)
    _row(p, "Call the dentist").locator("button[aria-label^='Delete']").click()
    p.wait_for_function("() => ![...document.querySelectorAll('.card.todo li.todo-row')].some(li => li.textContent.includes('Call the dentist'))")
    p.locator(".toast", has_text="Deleted").locator("button", has_text="Undo").click()
    _row(p, "Call the dentist").wait_for()
    assert card.locator("li.todo-row").count() == 4
    p.close()


def test_edit_text_due_and_steps_with_the_keyboard(browser):
    p = _open(browser)
    card = _panel(p)
    _row(p, "Call the dentist").locator("button[aria-label^='Edit']").click()
    form = card.locator(".todo-edit")
    form.wait_for()
    assert p.evaluate("() => document.activeElement.classList.contains('todo-text')")     # focus moves to the editor
    form.locator(".todo-text").fill("Call the dentist about a cleaning")
    form.locator(".todo-date").fill((date.today() + timedelta(days=2)).isoformat())
    form.locator("input[aria-label='New step']").fill("Find the dentist's number")
    form.locator("input[aria-label='New step']").press("Enter")
    form.locator("input[aria-label='New step']").fill("Call during lunch")
    form.locator("input[aria-label='New step']").press("Enter")
    _shot(p, "todo-edit")
    form.locator("button[type=submit]").click()
    row = _row(p, "about a cleaning")
    row.wait_for()
    assert "0/2 steps" in row.inner_text()
    row.locator(".todo-steps .cb").first.click()                         # tick a step off right in the list
    p.wait_for_function("() => [...document.querySelectorAll('.card.todo li.todo-row')].some(li => li.textContent.includes('1/2 steps'))")
    # Escape closes the editor without saving
    _row(p, "about a cleaning").locator("button[aria-label^='Edit']").click()
    card.locator(".todo-edit .todo-text").fill("SHOULD NOT SAVE")
    card.locator(".todo-edit .todo-text").press("Escape")
    p.wait_for_function("() => !document.querySelector('.card.todo .todo-edit')")
    assert _row(p, "SHOULD NOT SAVE").count() == 0
    p.close()


def test_tabs_sort_and_empty_state(browser):
    p = _open(browser)
    card = _panel(p)
    card.locator(".tabs button", has_text="Priority").click()
    first = card.locator("li.todo-row").first.locator(".tier").inner_text().lower()
    assert first == "high"
    card.locator(".tabs button", has_text="Overdue").click()
    assert card.locator("li.todo-row").count() == 1
    card.locator("li.todo-row .cb").first.click()                        # finish the only overdue one
    p.wait_for_function("() => (document.querySelector('.card.todo .empty') || {}).textContent?.includes('Nothing overdue')")
    card.locator(".tabs button", has_text="Done").click()
    assert card.locator("li.todo-row.is-done").count() == 2
    p.close()


def test_button_works_from_the_keyboard_and_reminders_show_in_the_app(browser):
    p = _open(browser)
    p.focus("#todoBtn")
    p.keyboard.press("Enter")
    p.wait_for_selector(".card.todo .todo-list")
    soon = (date.today()).isoformat() + "T23:59"
    item = {"id": "t2", "text": "Pick up package at the post office", "notes": "", "due": soon, "priority": "normal",
            "list": "", "status": "open", "steps": [], "source": "typed", "created": 0, "done_at": None}
    p.evaluate("ev => window.__monkeyEvents([ev])", ["todo_reminder", {"item": item}])
    toast = p.locator(".todo-remind")
    toast.wait_for()
    assert "Pick up package" in toast.inner_text() and toast.get_attribute("role") == "alert"
    toast.locator("button", has_text="Done").click()
    p.wait_for_function("() => ![...document.querySelectorAll('.card.todo li.todo-row')].some(li => li.textContent.includes('Pick up package'))")
    p.close()


def test_monkey_showing_the_list_opens_the_panel(browser):
    p = _open(browser)
    p.evaluate("ev => window.__monkeyEvents([ev])", ["todos", {"filter": "overdue"}])
    p.wait_for_selector(".card.todo .todo-list")
    assert p.locator(".card.todo .tabs:not(.sort) button.on").inner_text().startswith("Overdue")
    p.close()


@pytest.mark.parametrize("w,h", [(1280, 900), (420, 760)])
def test_no_serious_accessibility_problems_in_the_panel(browser, w, h):
    if not AXE.is_file():
        pytest.skip("axe-core not installed (npm ci in ui/)")
    p = _open(browser, w, h)
    _panel(p)
    p.fill("#todoNew", "finish essay by friday")
    _row(p, "Call the dentist").locator("button[aria-label^='Edit']").click()
    # colours are measured with opacity: let the entrance animations finish first (infinite shimmers excepted)
    p.wait_for_function("() => document.getAnimations().every(a => a.playState !== 'running' || "
                        "a.effect.getTiming().iterations === Infinity)")
    p.add_script_tag(content=AXE.read_text(encoding="utf-8"))
    bad = p.evaluate("""async () => (await axe.run('.card.todo', {resultTypes: ['violations']})).violations
        .filter(v => v.impact === 'serious' || v.impact === 'critical').map(v => v.id + ': ' + v.nodes.length)""")
    if w < 500:
        _shot(p, "todo-narrow")
    p.close()
    assert bad == [], bad


def test_every_header_button_fits_in_a_narrow_window(browser):
    """The To-do button made the header one button wider; at 420 px the buttons wrap instead of falling off."""
    p = _open(browser, 420, 760)
    off = p.evaluate("""() => [...document.querySelectorAll('#side > header button')]
        .filter(b => b.offsetParent !== null && b.getBoundingClientRect().right > innerWidth + 0.5).map(b => b.id)""")
    p.close()
    assert off == []


SMALL_DISPLAY_TEXT = """() => [...document.querySelectorAll('body *')].filter(el => {
    if (!el.offsetParent || ![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) return false;
    const cs = getComputedStyle(el);
    return cs.fontFamily.replace(/["']/g, '').startsWith('Titan One') && parseFloat(cs.fontSize) < 12;
  }).map(el => `${el.tagName.toLowerCase()}.${el.className} ${getComputedStyle(el).fontSize}: ${el.textContent.trim().slice(0, 30)}`)"""


def test_display_face_is_never_used_below_12px(browser):
    """App-wide fonts (ui/src/theme-blocky.css): the chunky display face only from 12 px up; smaller labels and
    badges use the text face at a heavy weight. Checked on the header, chat, to-do panel, Today and Settings."""
    p = _open(browser)
    p.evaluate("""() => window.__monkeyEvents([["user", {text: "what's due?"}], ["delta", {text: "Two things today."}], ["done", {}]])""")
    bad = p.evaluate(SMALL_DISPLAY_TEXT)
    _panel(p)
    bad += p.evaluate(SMALL_DISPLAY_TEXT)
    p.click("#todayBtn")
    p.wait_for_timeout(800)
    bad += p.evaluate(SMALL_DISPLAY_TEXT)
    p.click("#settingsBtn")
    p.wait_for_selector("dialog#settings[open]")
    bad += p.evaluate(SMALL_DISPLAY_TEXT)
    assert p.evaluate("() => getComputedStyle(document.body).fontFamily").replace('"', "").startswith("Nunito")
    p.close()
    assert bad == [], sorted(set(bad))


def test_blocky_skin_bakes_icons_and_stays_still_at_rest(browser):
    """The toy-block skin (ui/src/blocky/skin.ts, todo-blocky.ts, nav-blocky.ts): icons baked once by a short-lived renderer, played as CSS frames.
    `&blocky` forces the bake on this software-rendered browser (it is skipped on software GL otherwise). Asserts the
    decorations, that nothing animates in the panel at rest, that the check-off "pop" plays and the row still
    completes, that reduced motion plays no frames, and that a second launch uses the cached bake."""
    b, url = browser
    p = b.new_page(viewport={"width": 1280, "height": 900})
    _PAGES.append(p)
    p.set_default_timeout(30000)
    p.goto(url + "&blocky")
    p.wait_for_function("() => !!window.__monkeyEvents && !!window.__monkeyReady", timeout=20000)
    card = _panel(p)
    p.wait_for_selector(".card.todo.blocky", timeout=120000)      # software GL bakes slowly; a GPU takes a fraction of that
    stats = p.evaluate("() => window.__monkeyBlocky()")
    assert stats["failed"] == "" and stats["bytes"] > 0, stats
    assert card.locator(".cb .cb-ico").count() == card.locator(".cb").count() > 0
    assert card.locator("button[aria-label^='Delete'] .bi").count() == card.locator("button[aria-label^='Delete']").count()
    assert card.locator(".todo-add .primary .bi").count() == 1
    assert card.locator(".bk-bg").count() == 1
    p.wait_for_function("""() => document.querySelectorAll('#side > header .icon.labeled .bi').length >= 6
                                 && document.querySelectorAll('#mic .bi').length === 1""", timeout=120000)   # header + mic
                                                                    # (baked after the panel; slower on CI's software GL)
    assert p.locator("#todoBtn small").inner_text() == "To-do"                                                 # label kept
    assert card.locator("button[aria-label^='Edit Pick up package']").count() == 1    # accessible names unchanged
    running = ("() => document.getAnimations().filter(a => a.playState === 'running' && "
               "a.effect?.target?.closest?.('.card.todo')).length")
    p.wait_for_function(f"() => ({running})() === 0")              # after the background's one-shot fade-in: nothing runs
    cb = _row(p, "Pick up package").element_handle().query_selector(".cb")
    cb.click()
    assert p.evaluate("cb => cb.querySelector('.cb-ico').getAnimations().length", cb) == 1     # the "done!" pop
    p.wait_for_function("() => [...document.querySelectorAll('.card.todo .tabs button')].some(b => b.textContent === 'Done (2)')")
    p.emulate_media(reduced_motion="reduce")
    box = card.locator("li.todo-row .cb").first.element_handle()
    box.hover()
    assert p.evaluate("cb => cb.querySelector('.cb-ico').getAnimations().length", box) == 0
    p.reload()                                                     # same profile: the cached sheet, no WebGL
    p.wait_for_function("() => !!window.__monkeyEvents && !!window.__monkeyReady", timeout=20000)
    _panel(p)
    p.wait_for_selector(".card.todo.blocky", timeout=10000)
    assert p.evaluate("() => window.__monkeyBlocky().cached") is True
    p.close()
