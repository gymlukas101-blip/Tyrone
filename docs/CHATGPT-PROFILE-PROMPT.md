# Getting ChatGPT to hand over everything it knows about you (for Monkey's profile)

This is built from what works and what fails. Single "tell me everything about me" prompts come back **vague,
flattering, or half made up**:
- [Willison on "horoscope" answers](https://simonwillison.net/2024/Oct/15/chatgpt-horoscopes/)
- [invented facts, TechRadar](https://www.techradar.com/computing/artificial-intelligence/i-asked-chatgpt-to-make-an-image-describing-my-life-but-first-i-had-to-correct-some-errors)

ChatGPT also only *sees a synthesized summary* of your past chats. It can't search them word for word:
- [Willison](https://simonwillison.net/2025/May/21/chatgpt-new-memory/)
- [OpenAI memory FAQ](https://help.openai.com/en/articles/8590148-memory-faq)

So this sequence does three things:
- dumps saved memories **verbatim** first;
- then asks **one section per message**, with every fact **tagged by source and confidence**;
- then ends with a gaps and contradictions pass.

## Before you start (2 minutes)
1. **Turn memory on.** ChatGPT → Settings → Personalization: turn on **Reference saved memories** and **Reference chat history**. If either is off, you get very little back.
2. **Use a normal chat,** not a Temporary Chat.
3. **Use ChatGPT's best model** (a thinking model if you have one).
4. **Also request the full export:** Settings → Data controls → **Export data**. You get a ZIP by email; the link expires after 24 hours. Keep `conversations.json`, the only complete record. Monkey can mine it later for things ChatGPT's summary leaves out.
5. **Copy your memory list by hand:** Settings → Personalization → **Manage memories**. You'll use it to check Message 1.

Send the messages **one at a time** in the same chat, and wait for each answer.

---

### Message 1: verbatim dump
```
I'm moving my context to my personal AI assistant, so I need an exact copy of what you have stored about me.

1. List EVERY saved memory you have about me, word for word, exactly as stored. No summarizing, merging, or rewording.
2. Then list any custom instructions / "about me" / "how to respond" text I've set, word for word.
3. Then list anything else you are given about me in this conversation's context (for example a summary of my past chats or a profile), word for word as far as you can see it.

Put each part in its own code block. If a part is empty, say "EMPTY". Do not add commentary, compliments, or interpretation.
At the end, tell me honestly: is this the complete list, or are there things in your context you can't show or are unsure about?
```

### Message 2: identity, school and goals
```
Now build my profile section by section. Rules for every section from now on:
- Tag each item: [Saved memory], [From past chats], or [Inferred].
- Add confidence: High / Med / Low, and roughly when it came up (month/year) if you know.
- If you don't know something, write UNKNOWN. Do NOT guess or invent. Fewer true facts beat more invented ones.
- Neutral, factual tone. No compliments, no personality reading.
- Flag anything that might be outdated with (possibly outdated) and include contradictions you notice.
- Markdown: a heading per section, bullets underneath.

Section A: Identity & background (name I go by, age range, where I'm from, where I live, languages, anything about my upbringing or background I've shared).
Section B: School (university, year, major/minor, current and past classes, professors or TAs I've mentioned, grades or GPA goals, study habits, what I find hard or easy, schedule patterns).
Section C: Goals (this semester, this year, long term: career, academic, fitness, money, personal; why they matter to me if I said).
```

### Message 3: work, projects and tools
```
Same rules.

Section D: Work / business / side projects (jobs, internships, anything I'm building or selling, clubs or roles, what each involves, status, next steps, who's involved).
Section E: Current projects & open loops (anything in progress: status, deadline, my next step).
Section F: Tools, devices & accounts I use (phone, computer, apps, school systems like Canvas, email providers, calendars, AI tools, games, music services).
```

### Message 4: routines, health and people
```
Same rules.

Section G: Routines & schedule (wake/sleep times, class days, workouts, work shifts, weekly patterns, when I'm busiest, when I procrastinate).
Section H: Health & fitness (training style, sports, goals, diet, sleep, injuries or limitations I've mentioned). Only what I actually shared.
Section I: People in my life (first names + who they are to me + anything relevant I've said, e.g. roommate, family, friends, coworkers, professors). Only what I actually shared.
```

### Message 5: how I communicate and my rules
```
Same rules.

Section J: Communication style & preferences (how I like answers: length, tone, format, humor, slang, emoji; what annoys me in AI answers; how direct I want feedback).
Section K: My writing voice: describe how I write, then quote 5-10 short phrases or sentences I actually wrote to you (verbatim, mark each [Quote]). Do not paraphrase these.
Section L: Rules, boundaries & never-do list (things I've told you to always or never do, topics to avoid, privacy limits, how I want decisions or approvals handled).
Section M: Interests & tastes (hobbies, games, music, shows, food, sports teams, brands, things I like/dislike).
```

### Message 6: gaps, contradictions and inferences (kept separate on purpose)
```
Last pass.

1. What did you leave out of sections A-M, or what are you unsure about? List it.
2. List any contradictions or facts that changed over time (old -> new, with rough dates).
3. Separately, under a heading "Inferences (not stated)": what have you figured out about me that I never actually stated? Keep each to one line with a confidence level. These are guesses, so label them clearly.
4. Finally, combine EVERYTHING from this chat into ONE markdown document called "profile.md" inside a single code block, with sections A-M plus "Inferences (not stated)" and "Open questions". Keep all tags and confidence levels.
```

---

## After you have it
1. **Check it:**
   - Compare Message 1 with your **Manage memories** list.
   - Fix anything wrong.
   - Delete anything you don't want Monkey to know, especially health details and other people's information.
   - Keep **Inferences** separate. Monkey treats them as guesses, not facts.
2. **Give it to Monkey:**
   - Monkey → Settings → Memory → **Open folder**.
   - Save the final document as `profile.md`. If one already exists, paste it in under a heading like `## Imported from ChatGPT (2026-11)`.
   - Monkey reads this every conversation.
3. **Later:** the nightly "dream" pass (roadmap §2) will keep it current, dating facts and retiring stale ones. The `conversations.json` from your export can be mined for anything the summary missed.

**Privacy note:** this profile is sent to Claude as part of Monkey's context. Anthropic doesn't train on API data under its commercial terms. Still, leave out anything you'd never want an AI to have.
