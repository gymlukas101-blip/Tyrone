"""Courses the owner dropped (or hid): matching a spoken name to a Canvas course, and hiding it everywhere.

The setting `hidden_courses` is a list of entries {key, name, hidden_at, course_id, code, full, fact_id}. Only
`key`, `name` and `hidden_at` are required; the rest make matching robust when the source changes (a Canvas token
added later gives course ids the calendar feed didn't have). Everything is reversible: "show it again" removes the
entry and the hidden items come back as they were.

Matching a request ("marketing", "MKTG 777", "Marketing 777", "Intro to Marketing") to a course in the current feed,
strongest first:
  1. the course key or Canvas course id;
  2. a course code: department + number, with department words mapped to codes ("marketing" -> MKTG,
     "computer science" -> COMP SCI);
  3. the whole name (code, display name or Canvas's long name), ignoring case and punctuation;
  4. words: every meaningful word of the request must be a word of the course (its department, the department's
     subject words, or its long name). Whole words only, plus a prefix of 5+ letters ("psych") and one typo in
     long words ("marketting"). "Marketing" never matches "Mathematics".
The first tier with any match wins; two or more matches there are ambiguous and the caller asks which one.

Hiding an item (an assignment, a calendar event, a to-do, an email suggestion) never guesses wider than that: by
course id, by course code found in the text ("MKTG_777_001_F26", "mktg 777"), by the long name as a phrase, or by
a subject word next to a school word ("Marketing quiz", but not "marketing club meeting").
"""
from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Iterable

# Department codes (as Canvas shows them, spaces collapsed) -> the words people say for them. Made-up and common
# subjects only; nothing here is about any one person's schedule.
SUBJECTS: dict[str, tuple[str, ...]] = {
    "mktg": ("marketing",),
    "math": ("math", "maths", "mathematics", "calculus", "calc"),
    "stat": ("stat", "stats", "statistics"),
    "compsci": ("cs", "comp sci", "compsci", "computer science", "programming"),
    "chem": ("chem", "chemistry"),
    "biology": ("bio", "biology"),
    "bio": ("bio", "biology"),
    "physics": ("physics",),
    "psych": ("psych", "psychology"),
    "econ": ("econ", "economics"),
    "acctis": ("accounting",),
    "acct": ("accounting",),
    "finance": ("finance",),
    "fin": ("finance",),
    "genbus": ("business", "general business"),
    "mhr": ("management",),
    "mgmt": ("management",),
    "infosys": ("information systems",),
    "english": ("english", "writing"),
    "engl": ("english", "writing"),
    "history": ("history",),
    "hist": ("history",),
    "polisci": ("poli sci", "political science", "politics"),
    "soc": ("sociology",),
    "anthro": ("anthropology",),
    "philos": ("philosophy",),
    "phil": ("philosophy",),
    "commarts": ("comm arts", "communication arts", "communications", "comm"),
    "comm": ("communications", "comm"),
    "journ": ("journalism",),
    "art": ("art",),
    "arthist": ("art history",),
    "music": ("music",),
    "spanish": ("spanish",),
    "french": ("french",),
    "german": ("german",),
    "astron": ("astronomy",),
    "geog": ("geography",),
    "geosci": ("geology", "geoscience"),
    "ling": ("linguistics",),
    "kines": ("kinesiology",),
    "nutrsci": ("nutrition",),
    "envirst": ("environmental studies",),
    "ece": ("electrical engineering",),
    "me": ("mechanical engineering",),
    "lit": ("literature",),
}
# Spoken subject word -> department codes it can mean (several: "bio" is BIO or BIOLOGY, "finance" FIN or FINANCE).
WORD_TO_DEPTS: dict[str, set[str]] = {}
for _dept, _words in SUBJECTS.items():
    for _w in _words:
        WORD_TO_DEPTS.setdefault(_w, set()).add(_dept)

# Words that don't name a course ("hide all of my marketing assignments", "the class I dropped").
FILLER = {
    "a", "all", "an", "and", "any", "assignment", "assignments", "class", "classes", "course", "courses", "drop",
    "dropped", "every", "everything", "for", "from", "hide", "homework", "hw", "i", "i'm", "im", "in", "it", "just",
    "me", "my", "of", "on", "please", "remove", "show", "stuff", "that", "the", "this", "to", "work", "again", "lecture",
    "lectures", "section", "monkey", "canvas", "out",
}
SCHOOL_WORDS = re.compile(
    r"\b(?:quiz(?:zes)?|exams?|midterms?|finals?|homework|hw|assignments?|reading|readings|essays?|papers?|projects?|"
    r"lectures?|class(?:es)?|course|discussion|chapters?|ch|labs?|case stud(?:y|ies)|presentations?|problem sets?|"
    r"psets?|study|syllabus|textbook|module|recitation|lecture notes|office hours)\b", re.I)

# "MKTG_777_001_F26", "MKTG 777", "mktg777", "COMP SCI 400", "Marketing 777": department letters, then 3 digits.
_CODE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z&]*(?:[ _][A-Za-z&]+){0,3})[ _]?(\d{3})[A-Za-z]?(?![0-9])")


def norm(s: str) -> str:
    s = (s or "").lower().replace("&", " and ").replace("_", " ")
    s = re.sub(r"[^a-z0-9' ]+", " ", s).replace("'", "")
    return " ".join(s.split())


def _depts_for(words: list[str], upper_tail: bool) -> set[str]:
    """Department codes the last word(s) before a course number stand for: 'MKTG' -> {'mktg'}, 'comp sci' ->
    {'compsci'}, 'marketing' -> {'mktg'}, 'bio' -> {'bio', 'biology'}. An unknown all-caps code ('ZOOL') is itself."""
    for n in range(min(4, len(words)), 0, -1):
        tail = " ".join(words[-n:])
        if tail.replace(" ", "") in SUBJECTS:
            return {tail.replace(" ", "")}
        if tail in WORD_TO_DEPTS:
            return set(WORD_TO_DEPTS[tail])
    last = words[-1] if words else ""
    return {last} if upper_tail and last.isalpha() and 2 <= len(last) <= 8 else set()


def codes_in(text: str) -> set[str]:
    """Every course code in a text, as 'dept+number' keys: {'mktg777'}. Department words count ('Marketing 777')."""
    out: set[str] = set()
    for m in _CODE.finditer(text or ""):
        letters, num = m.group(1), m.group(2)
        raw_last = re.split(r"[ _]", letters)[-1]
        for d in _depts_for(norm(letters).split(), raw_last.isupper()):
            out.add(d + num)
    return out


def code_key(label: str) -> str:
    """The course code of a label ('MKTG 777' -> 'mktg777'), or ''. A code spelled out in letters wins over one
    from a subject word."""
    found = sorted(codes_in(label))
    flat = norm(label).replace(" ", "")
    for c in found:
        if c.rstrip("0123456789") in flat:
            return c
    return found[0] if found else ""


@dataclass
class Course:
    key: str                     # "canvas:<course id>" | "code:mktg777" | "name:<normalized>"
    name: str                    # what the owner sees: "MKTG 777"
    full: str = ""               # Canvas's long name when known: "Intro to Marketing"
    course_id: str = ""
    code: str = ""               # "mktg777"
    assignments: int = 0         # open + done items on the board
    open: int = 0

    def public(self) -> dict:
        return {"key": self.key, "name": self.name, "full": self.full, "assignments": self.assignments,
                "open": self.open}

    @property
    def dept(self) -> str:
        return self.code.rstrip("0123456789")

    @property
    def number(self) -> str:
        return self.code[len(self.dept):]

    def words(self) -> set[str]:
        """Every word that can name this course: department code, its subject words, long-name words, the number."""
        out: set[str] = set()
        if self.dept:
            out.add(self.dept)
            for w in SUBJECTS.get(self.dept, ()):
                out |= set(w.split()) | {w.replace(" ", "")}
        if self.number:
            out.add(self.number)
        for s in (self.full, self.name):
            out |= {w for w in norm(s).split() if w not in FILLER and len(w) > 1}
        return out


def course_key_for(course: str, course_id: str = "", full: str = "") -> str:
    if course_id:
        return f"canvas:{course_id}"
    code = code_key(course) or code_key(full)
    return f"code:{code}" if code else f"name:{norm(course or full)}"


def courses_from_items(items: Iterable[Any]) -> list[Course]:
    """The courses on the board (from Assignment objects or their dicts), with item counts."""
    by: dict[str, Course] = {}
    for it in items:
        g = (lambda k, d="": (it.get(k, d) if isinstance(it, dict) else getattr(it, k, d)))
        name, cid, full = str(g("course") or ""), str(g("course_id") or ""), str(g("course_name") or "")
        key = course_key_for(name, cid, full)
        c = by.get(key)
        if c is None:
            c = by[key] = Course(key=key, name=name or full or "Canvas", full=full if norm(full) != norm(name) else "",
                                 course_id=cid, code=code_key(name) or code_key(full))
        c.assignments += 1
        if not g("done", False):
            c.open += 1
    return sorted(by.values(), key=lambda c: c.name.lower())


# ------------------------------------------------------------------ resolving what the owner said
def _query_words(q: str) -> list[str]:
    return [w for w in norm(q).split() if w not in FILLER]


def _word_hit(w: str, have: set[str]) -> bool:
    if w in have:
        return True
    if len(w) >= 5 and any(h.startswith(w) for h in have):
        return True                                           # "psych" -> "psychology", "intro" -> "introduction"
    if len(w) >= 7:
        return any(len(h) >= 7 and SequenceMatcher(None, w, h).ratio() >= 0.88 for h in have)   # one typo
    return False


def resolve(query: str, courses: list[Course]) -> list[Course]:
    """The course(s) the owner meant. [] = no match; one = that course; several = ambiguous (ask which one)."""
    q = (query or "").strip()
    if not q or not courses:
        return []
    nq = norm(q)
    # 1. key or Canvas id
    hit = [c for c in courses if q == c.key or (c.course_id and nq in (c.course_id, f"canvas {c.course_id}"))]
    if hit:
        return hit
    # 2. course code ("MKTG 777", "Marketing 777", "mktg777")
    want = codes_in(q)
    if want:
        hit = [c for c in courses if c.code and c.code in want]
        if hit:
            return hit
        # "the 777 one": the number alone, when the department didn't say otherwise
        nums = {k.lstrip("abcdefghijklmnopqrstuvwxyz|") for k in want}
        depts = {k.rstrip("0123456789") for k in want}
        hit = [c for c in courses if c.number in nums and (not c.dept or c.dept in depts)]
        if hit:
            return hit
    # 3. the whole name
    stripped = " ".join(_query_words(q))
    hit = [c for c in courses if stripped and stripped in {norm(c.name), norm(c.full), c.code}]
    if hit:
        return hit
    # 4. words: every meaningful word must name the course
    words = [w for w in _query_words(q) if len(w) > 1]
    if not words:
        return []
    hit = [c for c in courses if all(_word_hit(w, c.words()) for w in words)]
    if hit:
        return hit
    # a number alone ("777")
    nums = [w for w in words if w.isdigit() and len(w) == 3]
    if nums and len(nums) == len(words):
        return [c for c in courses if c.number in nums]
    # 5. a subject word among other words the feed can't know ("Intro to Marketing" when Canvas only says
    #    MKTG 777): the courses in that department. Never a guess across departments, and never when the owner
    #    said a course number that isn't there ("Marketing 778").
    if want:
        return []
    depts: set[str] = set()
    for i, w in enumerate(words):
        for phrase in (" ".join(words[i:i + 2]), w):
            depts |= WORD_TO_DEPTS.get(phrase, set())
    if depts:
        return [c for c in courses if c.dept and c.dept in depts]
    return []


# ------------------------------------------------------------------ hidden entries
def _phrase_in(phrase: str, text_norm: str) -> bool:
    return bool(phrase) and len(phrase) >= 8 and len(phrase.split()) >= 2 and \
        re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text_norm) is not None


@dataclass
class HiddenCourses:
    """The `hidden_courses` setting, and the one test every surface uses: is this item from a hidden course?"""

    get: Callable[[], list]                       # -> the settings list
    put: Callable[[list], None]                   # saves the list
    now: Callable[[], datetime] = field(default=datetime.now)

    def entries(self) -> list[dict]:
        out = []
        for e in self.get() or []:
            if isinstance(e, dict) and e.get("key") and e.get("name"):
                out.append(e)
        return out

    def keys(self) -> set[str]:
        return {e["key"] for e in self.entries()}

    def __bool__(self) -> bool:                   # cheap "anything hidden?" for the hot paths
        return bool(self.entries())

    def find(self, key: str) -> dict | None:
        return next((e for e in self.entries() if e["key"] == key), None)

    def add(self, c: Course, fact_id: str = "") -> dict:
        rows = [e for e in self.entries() if e["key"] != c.key]
        e = {"key": c.key, "name": c.name[:80], "hidden_at": self.now().isoformat(timespec="minutes"),
             "course_id": c.course_id, "code": c.code, "full": c.full[:120], "fact_id": fact_id}
        rows.append(e)
        self.put(rows)
        return e

    def set_fact(self, key: str, fact_id: str) -> None:
        rows = self.entries()
        for e in rows:
            if e["key"] == key:
                e["fact_id"] = fact_id
        self.put(rows)

    def remove(self, key: str) -> dict | None:
        rows = self.entries()
        gone = next((e for e in rows if e["key"] == key), None)
        if gone is not None:
            self.put([e for e in rows if e["key"] != key])
        return gone

    def as_courses(self) -> list[Course]:
        return [Course(key=e["key"], name=e["name"], full=e.get("full", ""), course_id=e.get("course_id", ""),
                       code=e.get("code", "") or code_key(e["name"])) for e in self.entries()]

    # ---- the tests
    @staticmethod
    def _entry_matches_course(e: dict, course: str, course_id: str = "", full: str = "") -> bool:
        if e.get("course_id") and course_id and str(course_id) == str(e["course_id"]):
            return True
        if e["key"] == course_key_for(course, course_id, full):
            return True
        code = e.get("code") or code_key(e["name"])
        if code and code in (codes_in(course) | codes_in(full)):
            return True
        names = {norm(e["name"]), norm(e.get("full", ""))} - {""}
        return bool(names & ({norm(course), norm(full)} - {""}))

    def course_entry(self, course: str, course_id: str = "", full: str = "") -> dict | None:
        """The hidden entry an assignment's course belongs to, or None."""
        for e in self.entries():
            if self._entry_matches_course(e, course, course_id, full):
                return e
        return None

    def hides_course(self, course: str, course_id: str = "", full: str = "") -> bool:
        return self.course_entry(course, course_id, full) is not None

    @staticmethod
    def _text_matches(e: dict, text: str) -> bool:
        if not text:
            return False
        code = e.get("code") or code_key(e["name"])
        if code and code in codes_in(text):
            return True
        tn = norm(text)
        if _phrase_in(norm(e.get("full", "")), tn) or (not code and _phrase_in(norm(e["name"]), tn)):
            return True
        if tn in HiddenCourses._tag_names(e):
            return True                                  # the whole title is the course: "Marketing", "MKTG"
        # a subject word next to a school word: "Marketing quiz", "read ch 4 for marketing" (not "marketing club")
        dept = code.rstrip("0123456789") if code else ""
        subj = [w for w in SUBJECTS.get(dept, ()) if len(w) >= 4]
        if subj and SCHOOL_WORDS.search(text):
            return any(re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", tn) for w in subj)
        return False

    def text_entry(self, *texts: str) -> dict | None:
        """The hidden course a free text belongs to (an event title, a to-do, an email subject), or None."""
        for e in self.entries():
            if any(self._text_matches(e, t or "") for t in texts):
                return e
        return None

    def hides_text(self, *texts: str) -> bool:
        return self.text_entry(*texts) is not None

    def hides_event(self, ev: Any) -> bool:
        return bool(self.entries()) and self.hides_text(getattr(ev, "title", "") or "",
                                                       getattr(ev, "location", "") or "")

    def hides_todo(self, t: dict) -> bool:
        if not self.entries():
            return False
        origin = t.get("origin") or {}
        if isinstance(origin, dict) and origin.get("course_key") and self.find(origin["course_key"]):
            return True
        lst = norm(t.get("list") or "")
        for e in self.entries():
            if lst and lst in self._tag_names(e):
                return True
        return self.hides_text(t.get("text") or "", t.get("notes") or "",
                               (origin or {}).get("subject", "") if isinstance(origin, dict) else "")

    @staticmethod
    def _tag_names(e: dict) -> set[str]:
        """List tags that mean this course: '#mktg', '#mktg777', '#marketing', '#intro to marketing'."""
        code = e.get("code") or code_key(e["name"])
        dept = code.rstrip("0123456789") if code else ""
        out = {norm(e["name"]), norm(e["name"]).replace(" ", ""), norm(e.get("full", ""))}
        if code:
            out |= {code, dept}
            out |= {norm(w) for w in SUBJECTS.get(dept, ())}
        return out - {""}

    def hides_suggestion(self, s: dict) -> bool:
        return bool(self.entries()) and self.hides_text(s.get("text") or "", s.get("subject") or "",
                                                       s.get("evidence") or "")

    def filter_notes(self, text: str) -> str:
        """classes.md without the lines about a hidden class (so its times don't time the brief)."""
        if not self.entries() or not text:
            return text
        return "\n".join(ln for ln in text.splitlines() if not self.hides_text(ln))


def todos_for(todos: Iterable[dict], c: Course) -> list[dict]:
    """To-dos that belong to this course (by origin, list tag, code, long name or 'subject + school word')."""
    probe = HiddenCourses(lambda: [{"key": c.key, "name": c.name, "full": c.full, "course_id": c.course_id,
                                    "code": c.code}], lambda rows: None)
    return [t for t in todos if probe.hides_todo(t)]


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def fact_text(name: str, day: datetime | None = None) -> str:
    """The memory line ("Dropped MKTG 777 on 2026-11-24"). The name comes from Canvas: kept to plain words."""
    safe = re.sub(r"[^\w &:'().,/-]+", " ", name or "").strip()[:60] or "a class"
    return (f"Dropped {safe} on {(day or datetime.now()).date().isoformat()} "
            "(no longer one of their classes; Monkey hides it)")


# ------------------------------------------------------------------ dropping and showing again
class CourseDropper:
    """Drop (hide) a course everywhere and bring it back. Local Monkey data only: nothing on Canvas changes.

    preview(key) -> what would go (counts, the to-dos by name) and a one-time token; drop(key, token) does it:
    the course goes on the hidden list, its to-dos are archived (status 'dropped'), and a memory line says it was
    dropped (so Monkey stops talking about the class). undrop(key) reverses all three."""

    TOKEN_S = 15 * 60

    def __init__(self, hidden: HiddenCourses, board: Any, todos: Any = None,
                 memory_root: Callable[[], Any] | None = None, on_change: Callable[[dict], None] | None = None):
        self.hidden, self.board, self.todos = hidden, board, todos
        self.memory_root = memory_root
        self.on_change = on_change
        self._pending: dict[str, tuple[str, float]] = {}

    # ---- what's there
    def courses(self, refresh: bool = False) -> list[Course]:
        """Courses on the board that aren't hidden."""
        if self.board is None:
            return []
        return [c for c in self.board.courses(refresh=refresh)
                if not self.hidden.hides_course(c.name, c.course_id, c.full)]

    def resolve(self, query: str) -> list[Course]:
        return resolve(query, self.courses())

    def resolve_hidden(self, query: str) -> list[Course]:
        return resolve(query, self.hidden.as_courses())

    def _course(self, key: str) -> Course | None:
        return next((c for c in self.courses() if c.key == key), None)

    def _todos(self, c: Course) -> list[dict]:
        return todos_for(self.todos.items("all"), c) if self.todos is not None else []

    # ---- preview + drop
    def preview(self, key: str) -> dict:
        c = self._course(key)
        if c is None:
            return {"ok": False, "error": "That class isn't on your Homework list any more."}
        todos = self._todos(c)
        token = secrets.token_urlsafe(12)
        self._pending[key] = (token, time.time())
        return {"ok": True, "key": c.key, "name": c.name, "full": c.full, "assignments": c.assignments,
                "todos": [{"id": t["id"], "text": t["text"]} for t in todos], "token": token,
                "say": f"Hide {c.name} everywhere? {plural(c.assignments, 'assignment')}, "
                       f"{plural(len(todos), 'to-do')}."}

    def drop(self, key: str, token: str) -> dict:
        want = self._pending.get(key)
        if not want or not token or not secrets.compare_digest(want[0], str(token)) \
                or time.time() - want[1] > self.TOKEN_S:
            return {"ok": False, "error": "Confirm it again (the confirmation expired)."}
        self._pending.pop(key, None)
        c = self._course(key)
        if c is None:
            return {"ok": False, "error": "That class isn't on your Homework list any more."}
        todos = self._todos(c)
        self.hidden.add(c)
        archived = self.todos.archive_for_course([t["id"] for t in todos], c.key) if self.todos is not None else []
        fact_id = self._remember(c)
        if fact_id:
            self.hidden.set_fact(c.key, fact_id)
        out = {"ok": True, "action": "dropped", "key": c.key, "name": c.name, "full": c.full,
               "assignments": c.assignments, "todos": [{"id": t["id"], "text": t["text"]} for t in archived],
               "say": f"Removed {plural(c.assignments, c.name + ' assignment')} and "
                      f"{plural(len(archived), 'to-do')}."}
        self._changed(out)
        return out

    def undrop(self, key: str) -> dict:
        e = self.hidden.remove(key)
        if e is None:
            return {"ok": False, "error": "That class isn't hidden."}
        restored = self.todos.restore_course(key) if self.todos is not None else []
        self._forget(e.get("fact_id", ""))
        n = self._count(key)
        out = {"ok": True, "action": "restored", "key": key, "name": e["name"], "assignments": n,
               "todos": [{"id": t["id"], "text": t["text"]} for t in restored],
               "say": f"{e['name']} is back: {plural(n, 'assignment')} and {plural(len(restored), 'to-do')}."}
        self._changed(out)
        return out

    def _count(self, key: str) -> int:
        try:
            return len(self.board.items_for(key)) if self.board is not None else 0
        except Exception:  # noqa: BLE001
            return 0

    def hidden_list(self) -> list[dict]:
        archived = self.todos.items(DROPPED_STATUS) if self.todos is not None else []
        return [{"key": e["key"], "name": e["name"], "full": e.get("full", ""), "hidden_at": e.get("hidden_at", ""),
                 "assignments": self._count(e["key"]),
                 "todos": sum(1 for t in archived if t.get("dropped_course") == e["key"])}
                for e in self.hidden.entries()]

    # ---- memory (the one fact-writing path: facts.add_fact / forget_fact)
    def _remember(self, c: Course) -> str:
        root = self.memory_root() if self.memory_root else None
        if not root:
            return ""
        from ..memory import facts as F

        try:
            f, _ = F.add_fact(Path(root), "classes.md", fact_text(c.name, self.hidden.now()), src="user_said")
            return f.id
        except Exception:  # noqa: BLE001 - hiding works without the note
            return ""

    def _forget(self, fact_id: str) -> None:
        root = self.memory_root() if self.memory_root else None
        if not root or not fact_id:
            return
        from ..memory import facts as F

        try:
            F.forget_fact(Path(root), fact_id)
        except Exception:  # noqa: BLE001 - already gone (edited by hand)
            pass

    def _changed(self, summary: dict) -> None:
        if self.on_change is not None:
            try:
                self.on_change(summary)
            except Exception:  # noqa: BLE001 - the change is saved; a refresh hiccup must not undo the answer
                pass


DROPPED_STATUS = "dropped"

