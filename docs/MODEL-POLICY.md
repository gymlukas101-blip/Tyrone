# Monkey's model policy: which Claude model + effort for each task (researched and calibrated 2026-11-18)

Monkey routes every request to a **task**, then reads that task's model and effort from a stored policy:
- shipped defaults: `monkey/brain/model_policy.json`
- your changes and calibration results: `%APPDATA%\Monkey\model_policy.json`, which survives updates

Each task has three settings:

| Setting | Used when | Meaning |
|---|---|---|
| **⚡ Quick** (`min`) | You press ⚡ or say "quick" | The cheapest model and effort that still does the job well |
| **Auto** (`default`) | Normally | The best value |
| **★ Important** (`max`) | You press ★ or say "this is important" | The most that's worth paying for. Higher settings cost much more for little gain on these tasks |

You can see and change all of it in **Settings → Brain → 🧠 Open model table**. Monkey also keeps a readable copy in his memory (`model_policy.md`), so you can ask him "which model do you use for emails?".

## The table
Generated with `python -m tools.model_policy.report`.

- "First words" = seconds until Monkey starts speaking.
- Slow tasks also get an instant spoken holding line ("Pulling up your day."), so you're never left in silence.
- Monthly figures assume heavy student use, e.g. 20 chats/day, 4 web lookups/day, 1–2 email drafts/day, 1 research request/day.

| Task | ⚡ Quick (min) | **Auto (default)** | ★ Important (max) | Auto cost / use | First words | Auto / month |
|---|---|---|---|---|---|---|
| Chit-chat / small talk | Haiku 5.5 · low ($0.0001) | **Haiku 5.5 · low** | Sonnet 5.5 · low ($0.0018) | $0.0001 | 0.7s | $0.080 |
| Quick fact (no web) | Haiku 5.5 · low ($0.0002) | **Haiku 5.5 · medium** | Sonnet 5.5 · medium ($0.0042) | $0.0002 | 1.7s | $0.070 |
| Commands (open a site, pictures, videos, time, emote) | Haiku 5.5 · low ($0.0003) | **Haiku 5.5 · low** | Sonnet 5.5 · low ($0.0041) | $0.0003 | 1.8s | $0.080 |
| Weather | Haiku 5.5 · low ($0.0004) | **Haiku 5.5 · low** | Sonnet 5.5 · low ($0.0057) | $0.0004 | 1.8s | $0.020 |
| Quick web lookup (scores, hours, news) | Haiku 5.5 · medium ($0.016) | **Haiku 5.5 · medium** | Sonnet 5.5 · medium ($0.038) | $0.016 | 5.4s | $2.43 |
| Canvas assignments / what to work on | Haiku 5.5 · low ($0.0007) | **Haiku 5.5 · medium** | Sonnet 5.5 · medium ($0.014) | $0.0008 | 3.4s | $0.100 |
| Check off an assignment | Haiku 5.5 · low ($0.0003) | **Haiku 5.5 · low** | Sonnet 5.5 · low ($0.0035) | $0.0003 | 1.8s | $0.020 |
| To-do list (add, check off, help with an item) | Haiku 5.5 · low ($0.0003) | **Haiku 5.5 · medium** | Sonnet 5.5 · medium ($0.0068) | $0.0004 | 2.7s | $0.050 |
| Dropped a class (hide it everywhere / show it again) | Haiku 5.5 · low ($0.0003) | **Haiku 5.5 · low** | Sonnet 5.5 · low ($0.0037) | $0.0003 | 1.8s | $0.0000 |
| Task helper (unsubscribe, do something on a website) | Haiku 5.5 · low ($0.0003) | **Haiku 5.5 · medium** | Sonnet 5.5 · medium ($0.0063) | $0.0004 | 2.5s | $0.020 |
| Garmin sleep / heart rate | Haiku 5.5 · low ($0.0005) | **Haiku 5.5 · medium** | Sonnet 5.5 · medium ($0.011) | $0.0006 | 3.0s | $0.040 |
| Calendar (what's on today) | Haiku 5.5 · low ($0.0005) | **Haiku 5.5 · low** | Sonnet 5.5 · medium ($0.011) | $0.0005 | 2.0s | $0.040 |
| Remember / forget something | Haiku 5.5 · low ($0.0003) | **Haiku 5.5 · low** | Sonnet 5.5 · low ($0.0042) | $0.0003 | 1.8s | $0.020 |
| Everyday question (no rule matched) | Haiku 5.5 · low ($0.0033) | **Haiku 5.5 · medium** | Opus 5.5 · medium ($0.022) | $0.0035 | 3.6s | $0.700 |
| Read and summarize an email | Haiku 5.5 · medium ($0.0011) | **Sonnet 5.5 · low** | Opus 5.5 · medium ($0.040) | $0.017 | 5.6s | $1.05 |
| Email & calendar triage (ranking) | Haiku 5.5 · high ($0.0050) | **Sonnet 5.5 · medium** | Opus 5.5 · medium ($0.150) | $0.075 | 19.4s | $3.37 |
| Daily briefing (my day / my week) | Sonnet 5.5 · medium ($0.032) | **Sonnet 5.5 · medium** | Opus 5.5 · medium ($0.063) | $0.032 | 8.4s | $0.950 |
| Study help / explain a concept | Sonnet 5.5 · medium ($0.015) | **Sonnet 5.5 · medium** | Opus 5.5 · high ($0.053) | $0.015 | 9.0s | $1.32 |
| Hard reasoning (proofs, tricky problems, planning) | Sonnet 5.5 · medium ($0.016) | **Opus 5.5 · medium** | Opus 5.5 · high ($0.050) | $0.032 | 9.5s | $0.960 |
| Draft an email in your voice | Opus 5.5 · low ($0.055) | **Opus 5.5 · medium** | Opus 5.5 · high ($0.084) | $0.064 | 14.7s | $2.90 |
| Deep research | Sonnet 5.5 · medium ($0.176) | **Opus 5.5 · medium** | Opus 5.5 · high ($0.392) | $0.302 | 55.9s | $9.07 |
| Make a picture (writing the image prompt) | Haiku 5.5 · low ($0.0003) | **Haiku 5.5 · low** | Sonnet 5.5 · low ($0.0053) | $0.0003 | 1.9s | $0.010 |
| Router (which task is this?) | Haiku 5.5 · low ($0.0001) | **Haiku 5.5 · low** | Haiku 5.5 · low ($0.0001) | $0.0001 | 0.6s | $0.020 |
| Find to-dos in email (background) | Haiku 5.5 · low ($0.0003) | **Haiku 5.5 · low** | Haiku 5.5 · low ($0.0003) | $0.0003 | 0.6s | $0.030 |
| Inbox cleanup: emails it isn't sure about (background) | Haiku 5.5 · low ($0.0004) | **Haiku 5.5 · low** | Haiku 5.5 · low ($0.0004) | $0.0004 | 0.6s | $0.0000 |
| Learn my writing style (one time) | Sonnet 5.5 · high ($0.230) | **Opus 5.5 · medium** | Opus 5.5 · high ($0.460) | $0.400 | 28.1s | $0.0000 |
| Computer task planner (background) | Sonnet 5.5 · medium ($0.0075) | **Sonnet 5.5 · medium** | Opus 5.5 · medium ($0.015) | $0.0075 | 1.0s | $1.12 |

Monthly totals (heavy use): Auto **$24.47**, all Quick $15.56, all Important $54.22.

The policy also has five internal tasks that don't show up as chat requests:
- **Router:** classifies requests that no rule catches.
- **Find to-dos in email:** the background inbox scan for "Suggested from email". It runs only on new mail that passed
  the local filter, at most once per scan, gets no tools, and is skipped at 90% of the monthly budget.
- **Inbox cleanup (emails it isn't sure about):** local rules (`monkey/inbox/rules.py`) decide almost every email.
  Only bulk mail that asks for something but names no date goes to the model: at most 20 per plan, subject + sender
  name + Gmail's short preview, no tools, skipped at 90% of the budget. Anything it isn't sure about stays.
- **Learn my writing style:** runs once.
- **Computer task planner:** plans 1–4 steps of a general computer task per call (`computer/goal.py`, ClaudeGoalPlanner):
  `default` is the planner, `max` is the one stall escalation. Deterministic steps (the course skill, cached verified
  steps, the mailing-list unsubscribe page) make no model call. The per-task budget (40 calls, $1) still applies.

**Task helper** (2026-11-23): the chat route for "unsubscribe me from…", "cancel my … trial", "do X on website Y". The
reply is one tool call (`propose_computer_task`, `find_mailing_lists` or `propose_unsubscribe`) and a line, so Haiku is
enough; the work itself is the computer task planner above. Finding mailing lists and one-click unsubscribes need no
model at all.

The numbers come from the Settings → Brain screen and are the same as above.

## Calibration results (2026-11-18, $1.10, one sample per setting)
What the first real calibration run showed, and what changed because of it:

| Task | Result | Decision |
|---|---|---|
| Chit-chat, quick facts, commands, weather, check-off, memory, pictures | Haiku matched Sonnet's answers at about 1/12 the cost and as fast or faster | Haiku (pictures moved to low) |
| Calendar | Identical answers; Haiku low fastest (1.8 s) | **Changed to Haiku low** |
| Everyday questions | Haiku medium was as good as Sonnet low ($0.0004 vs $0.005, 3 s vs 5.4 s) | **Changed to Haiku medium** |
| Web lookup | Same facts; Haiku $0.012 / 11 s vs Sonnet $0.051 / 16 s | Haiku medium |
| Canvas, Garmin | All accurate; Haiku medium explained grade weights best | Haiku medium |
| Read an email | All accurate; Sonnet offered to draft a reply | Sonnet low. It costs about $0.50/month more, but real emails are messier |
| Email triage | Sonnet medium clearly best; Haiku mixed in non-emails | Sonnet medium |
| Daily briefing | Sonnet medium excellent (6 s, $0.01); Opus slower, not better | Sonnet medium |
| Study help | Sonnet medium good; Opus high more exam-focused at 3x the cost | Sonnet medium, with Opus high as ★ Important |
| Hard reasoning | Opus medium sharpest (caught a wrong due date) at about Sonnet's cost | Opus medium |
| Email drafts | All Opus settings behaved well and cost about the same | Opus medium. Re-test with the drafts visible (now shown in results) |
| Deep research | Biggest gap: Sonnet generic; Opus medium specific and engineering-aware ($0.21, 55 s); Opus high no better | Opus medium |

Caveats from that run:
- **Cold cache:** the first request to each model was inflated by writing the prompt cache. Calibration now sends an untimed warm-up first.
- **Stubbed ranking:** triage's ranking step was stubbed, but now really runs.
- **Hidden drafts:** email drafts weren't visible, and now are.
- **Wrong guesses about people:** models assumed a professor's gender. The persona now says not to.
- **Over-sharing in small talk:** Haiku listed tasks in reply to small talk. The persona now says to keep small talk short and offer instead.
- **Small fake data:** with real data, costs are a bit higher than measured. Measured heavy-use total: about $15–17/month.

## Why each choice (the short version)
- **Everyday talk, commands, Canvas, Garmin, calendar, weather and memory notes → Haiku 5.5.**
  - The data is fetched and ranked by code (grade impact, sleep numbers, events). The model only has to say it nicely.
  - Haiku is the fastest model (about 0.7 s to first words for chat) and costs about 1/20 of Sonnet.
  - Anthropic's guidance: Haiku at `low` for chat and short tool tasks.
- **Quick web lookups → Haiku 5.5 with web search.**
  - Haiku 5.5 supports web search, so Monkey's old "no web for Haiku" rule is gone.
  - Monkey gives it today's date plus Anthropic's recommended nudge to search for anything that may have changed.
  - Every search costs $0.01 on any model, so most of this task's cost is the search itself.
- **Everyday questions with no specific task → Haiku 5.5 medium** (changed after calibration).
  - Same quality as Sonnet on the test, faster and cheaper. Hard questions still go to Opus.
- **Reading and summarizing an email → Sonnet 5.5 low.**
  - Needs judgment about someone else's writing.
- **Triage and ranking of email and calendar → Sonnet 5.5 medium, plus "think the problem through first".**
  - That's Anthropic's advice for structured-output reasoning tasks.
  - It replaced the old hard-coded Opus at about half the price.
- **Briefings and study help → Sonnet 5.5 medium.**
  - Study help goes up to Opus high when you say it's important (exam prep).
- **Hard reasoning and email drafts in your voice → Opus 5.5 medium.**
  - This is where Opus's extra reasoning and writing quality pays off.
  - Drafts are always approved by you before sending.
- **Deep research → Opus 5.5 medium.**
  - Anthropic's research benchmarks: `medium` matched `high` for less, and `low` gave up only a little.
  - `xhigh`, `max` and Fable 5.2 cost 2–3x for little gain here.
- **Never automatic:** Fable 5.2 ($8/$40 per million tokens, moderate speed) and `xhigh`/`max` effort. You can still pick them in the table if you want.
- **Gathering Canvas, Google, Outlook and Garmin updates costs $0.** That's plain code calling those services. Only the spoken summary uses Claude.

## Speed and cost tricks in the code
- **Prompt caching:** the persona and tool definitions (about 4k tokens) are cached for 1 hour. Repeats cost 5% of the input price on Opus and Sonnet, 10% on Haiku.
- **Effort changes don't break the cache.** The first request fixes the conversation's top-level effort. Later turns change effort with a per-message system message (beta `mid-conversation-output-config-2026-07-01`), which keeps the cache. If the API rejects it, Monkey falls back to plain effort automatically.
- **Sticky model:** a quick follow-up within 2 minutes stays on the model that just answered, as long as that model is inside the new task's Quick–Important range. Caches are per model, so switching up to Opus would re-pay the whole conversation (about $0.075 for 15k tokens, versus $0.003 to stay).
- **No memory round trip:** `profile.md` and the memory file list go into the first turn directly, which saves about 1 s and one API call per conversation.
- **Holding lines:** slow tasks (briefing, study help, hard problems, drafts, research) say a short line immediately.

## Calibrate (measure instead of estimate)
**Settings → Brain → Calibrate models** works like this:
1. It sends one untimed warm-up request per model, then runs one sample request per task on each of its Quick, Auto and Important settings. That's about 50 runs, about 5 minutes, and about $1–3 of API credits; the exact estimate is shown before you confirm. Tick "2 samples each" for steadier numbers at about 2x the cost, or re-run only the tasks you tick on the results page.
2. Canvas, Garmin, email and calendar data are **fake**, and the draft and send tools are stubbed, so nothing real is read, sent or changed. Web search and the triage ranking step are real.
3. It records real cost, time to first words and total time, then shows the answers side by side, including the email drafts and on-screen content each model produced.
4. For each task, you pick the best answer (it becomes Auto) or leave "All fine" (the cheapest is kept).
5. The measured numbers appear in the table and in Monkey's memory note.

Re-run it when new Claude models come out or if a task's answers start to feel off.

## How the estimates are calculated
`monkey/brain/policy.py` → `estimate()` uses:
- About 4k cached prefix tokens (persona, tool definitions, and the 286-token tool system prompt) plus about 3k tokens of earlier conversation, read from cache on every round.
- Each task's new input (tool results sized from Monkey's real tools), written to cache at 1.25x.
- Visible output plus thinking. Thinking is scaled by effort: low 0.3x, medium 1x, high 2.5x, xhigh 5x, max 8x.
- About 60 tokens of tool-call output per extra round, and web searches at $0.01 each.
- Speed: Haiku about 230 tokens/s, Sonnet about 100, Opus about 75, plus 0.5 / 0.8 / 1.2 s startup.

Expect about ±50% accuracy, which is why calibration exists.

## Sources
- Anthropic, Models overview (latency class, default effort, pricing): https://platform.claude.com/docs/en/models/overview
- Anthropic, Pricing (cache read 0.05x on Opus/Sonnet 5.5, tool system prompt 286 tokens, web search $10/1k): https://platform.claude.com/docs/en/about-claude/pricing
- Anthropic, Effort (per-model recommendations, per-message effort keeps the cache): https://platform.claude.com/docs/en/build-with-claude/effort
- Anthropic, Web search tool (supported models include Haiku 5.5): https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool
- Anthropic, Prompting Claude Haiku 5.5 (search nudge, low for chat): https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-haiku-5-5
- Anthropic, Prompting Claude Sonnet 5.5 (low/medium for chat, "think first" for JSON reasoning): https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5-5
- Output speed (third-party; numbers vary by test setup): Artificial Analysis https://artificialanalysis.ai/providers/anthropic and DeepLearning.AI https://www.deeplearning.ai/the-batch/claude-fills-out-its-model-family/
