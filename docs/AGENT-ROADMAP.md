# Monkey: agent roadmap (harness, memory, skills, tools, channels, voice, subagents, routines)

Researched 2026-11-18 by four parallel research passes (sources inline). Each section gives a **verdict for Monkey**,
because Monkey already has much of what the viral "agentic AI stack" posts describe.

## 0. Where Monkey already is

| Layer from the post | Monkey today |
|---|---|
| **Harness** (plan → act → check loop) | Yes. A Claude tool-use loop with streaming, up to N tool rounds, escalation to a stronger model, an approval gate before any email is sent, rollback and repair when a turn fails, and per-task routing between Haiku, Sonnet and Opus with an effort level. |
| **Memory** | Partly. Anthropic's memory tool writes markdown files (`%APPDATA%\Monkey\memory`), and a conversation survives restarts. It does **not** yet remember *past* conversations or consolidate what it learns. |
| **Skills** | No. Task behavior lives in the persona and the router. |
| **Tools** | 16 tools: Gmail and Outlook (drafts), Google Calendar, Canvas (ICS), Garmin, weather, web search and fetch, websites, images, video, ranking. |
| **Channels** | Desktop only: voice and typing. |
| **Subagents** | No. |
| **Routines** | No scheduler. |

---

## 1. "Without a harness it's just a chatbot": is it true, and should we install Hermes Agent?

**Mostly true:**
- A model only acts as an agent inside a loop that calls tools and checks results.
- The *quality* of that loop matters. With the model held fixed, changing only the harness moved Terminal-Bench 2 from 69.7% to 77.0%. Scaffolds alone vary by up to about 15 points on SWE-bench ([preprint](https://arxiv.org/abs/2605.23950), figures from search snippets; [secondary](https://codex.danielvaughan.com/2026/04/19/the-harness-effect-same-model-different-tool-different-score/)).
- Anthropic's own guidance points at specific design choices, not brands: tool descriptions, keeping only the context that matters (fetched just in time), compaction, notes/progress files, and an end-to-end verify step ([building effective agents](https://www.anthropic.com/research/building-effective-agents), [context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), [long-running harnesses](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)). Rewriting tool descriptions alone cut task time by 40% ([multi-agent post](https://www.anthropic.com/engineering/multi-agent-research-system)).

**The post is almost certainly about Nous Research's [Hermes Agent](https://github.com/NousResearch/hermes-agent):**
- MIT license; a memory it curates itself, optionally backed by Honcho; skills it writes for itself; messaging gateways; cron; subagents; Windows support.
- It has an injection CVE in its Skills Guard ([CVE-2026-9353](https://advisories.gitlab.com/pypi/hermes-agent/CVE-2026-9353/)).

**OpenClaw:** similar, with a poor security record:
- credentials stored in plaintext;
- remote code execution ([CVE-2026-25253](https://www.kaspersky.com/blog/openclaw-vulnerabilities-exposed/55263/));
- [341 malicious marketplace skills](https://thehackernews.com/2026/02/researchers-find-341-malicious-clawhub.html);
- and since April 2026 your Claude Max subscription doesn't cover it.

**Verdict: don't install either one as Monkey's brain. Keep Monkey's loop and borrow the patterns.**
- **What you'd gain:** messaging gateways, a scheduler and a skills format. All three are small to build into Monkey (sections 4, 6 and 9).
- **What you'd lose:** the voice and avatar app, the email approval gate, cost routing, and safety (a large attack surface).
- **Self-written skills don't help.** In SkillsBench, skills the agent wrote for itself scored −1.3 points on average, while human-written skills scored +16 ([SkillsBench](https://arxiv.org/abs/2602.12670)). Their headline feature is the weak part.

**Genuine harness upgrades to make in Monkey:**
1. A **verify step** on multi-step tasks: re-read the draft or calendar result before saying "done".
2. **Progress notes** for long tasks.
3. Rewrite the **tool descriptions** using Anthropic's guidance (cheap, measurable with the existing calibration harness).
4. **Drop the separate Haiku classifier call.** Let Haiku answer directly and escalate through the existing `escalate` tool. This saves about 0.6–1 s on every request.

## 2. Persistent memory: Honcho ("Hancho AI"), Obsidian, or something else?

- **"Hancho AI" is Honcho by Plastic Labs:**
  - It builds "representations" of you in the background, with experimental "dreaming".
  - It's hosted (about $2 per million tokens ingested, reads free) or self-hosted (AGPL, needs Postgres + pgvector) ([GitHub](https://github.com/plastic-labs/honcho)).
  - It reports 90%+ on memory benchmarks, but those runs are vendor-run, and an independent recount puts its real lead at about 6 points ([recount](https://techsy.io/en/blog/honcho-memory-review)).
- **mem0, Letta and Zep:** more infrastructure, with no independently verified quality gain for one user.
- **Claude app memory:** it can't be reached from the API.
- **Obsidian:** a vault is just a folder of markdown, which is exactly what Monkey's memory already is.

**Verdict: keep Monkey's markdown memory and add the three missing pieces.** Storage was never the gap; recalling past conversations and consolidating them is.

1. **Episode log (stops repeating yourself).** At the end of each conversation, Monkey writes `episodes/YYYY-MM-DD.md` with:
   - topics;
   - decisions;
   - open loops;
   - "things you already told me".

   Raw transcripts go into the local database it already keeps.
2. **Search past conversations.** Use local embeddings (sqlite-vec plus a small embedding model) behind a `search_past_conversations` tool. Monkey fetches history *on demand* instead of stuffing it into every prompt.
3. **Nightly "dream" pass (gets sharper over time).** A routine that:
   - merges episodes into `profile.md`;
   - dates every fact ("as of 2026-11");
   - retires stale facts;
   - keeps the profile under about 2k tokens, so it stays cheap and cached.
4. **Make the folder an Obsidian vault,** so you can read and fix memory on your phone.
   - Use exactly **one** sync service. Obsidian Sync is about $4–5/month; Remotely Save to Dropbox is free.
   - Don't also point OneDrive at the same folder, and avoid iCloud on Windows ([forum](https://forum.obsidian.md/t/meta-post-syncing-between-devices/20983)).
5. **Honcho (optional):** a two-week side-by-side trial later, only if (1)–(3) still feel shallow.

**Safety:**
- Memory can be poisoned by emails and web pages ([ICML 2026](https://icml.cc/virtual/2026/67842)).
- **Never write memory in a turn that has email or web content in context.** Tag where each fact came from, and let the nightly pass flag anything that came from an email.
- Keep Garmin health facts in their own file, outside the cloud-synced vault.

## 3. Teach it who you are: the ChatGPT profile export

See **[docs/CHATGPT-PROFILE-PROMPT.md](CHATGPT-PROFILE-PROMPT.md)**. It's a 6-message sequence built from what works and what fails in practice:
- **Verbatim dump first:** saved memories word for word.
- **One section per message:** single "tell me everything" prompts come back vague and flattering.
- **Every fact tagged:** [Saved memory] / [From past chats] / [Inferred], plus a confidence level and "UNKNOWN" instead of guesses.
- **A gaps and contradictions pass** at the end.

Also download the **official export** (ChatGPT → Settings → Data controls → Export data). It's the only *complete* record. Monkey can later mine `conversations.json` for a fuller profile than ChatGPT's own summary, which OpenAI admits is "broader than what can be shown."

## 4. Skills: folder + SKILL.md, loaded only when needed

How Anthropic's Agent Skills work ([docs](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)):
- Each skill's **name and description** sit in the prompt, about 100 tokens each.
- The **SKILL.md body** loads when the skill is triggered.
- **Scripts and reference files** load only when needed.

The API version runs in a container **with no network**, so it can't touch Gmail, Canvas or Calendar. **Monkey should implement the same open format itself:**
- scan `skills/*/SKILL.md`;
- list the names and descriptions in the cached system prompt;
- add a `load_skill(name)` tool.

Evidence: human-written, focused skills of 2–3 modules work best, at **+16 points** on average; some tasks got worse, so evaluate each skill with the calibration harness ([SkillsBench](https://arxiv.org/abs/2602.12670)).

### Skill architecture: your work in branches, each branch a set of skills
*(Fill the business/work branch from the ChatGPT profile.)*

```
skills/
  school/
    canvas-triage/SKILL.md        what's due, what's worth the most points, what to do first
    study-session/SKILL.md        explain → quiz → spaced review for a class topic
    exam-prep/SKILL.md            build a study plan backward from the exam date
    email-professor/SKILL.md      extension / question emails in the right tone (draft only)
    paper-feedback/SKILL.md       rubric-based feedback on a draft, never writes it for you
  inbox-and-calendar/
    inbox-triage/SKILL.md         rank, summarize, propose replies
    reply-in-my-voice/SKILL.md    uses writing samples from memory
    plan-my-week/SKILL.md         classes + deadlines + workouts → time blocks (asks before booking)
  health/
    recovery-check/SKILL.md       Garmin sleep/HRV → train hard / easy / rest
    workout-plan/SKILL.md
  career/
    internship-search/SKILL.md    (uses research subagents, section 8)
    resume-tailor/SKILL.md
  life-admin/
    errands-and-bills/SKILL.md    reminders only, never pays anything
  work-or-business/               ← from your ChatGPT profile
```

Each skill folder has:
- `SKILL.md`: frontmatter with `name` and a one-line `description` of *when* to use it, then the steps, rules and an output format;
- optionally a `reference.md` and examples.

## 5. Tools: what to connect, in order of value for effort

1. **Canvas REST API.** Since **Nov 14, 2025, UW-Madison students can't create Canvas tokens themselves.** You request one through a form, and it arrives through 1Password ([KB](https://kb.wisc.edu/156712)).
   - **Action for you: submit that request now** (there's a lead time).
   - It unlocks grades, announcements and submission status. The ICS feed covers due dates until then.
2. **Google Drive, Docs and Sheets.** The direct API reuses Monkey's existing Google OAuth. Google's hosted Workspace MCP servers are still in developer preview.
3. **Tasks that sync to your phone.** Todoist has an official API and a personal token; Google Tasks is the alternative. Apple Reminders has no web API.
4. **A browser for logged-in sites.** Use Microsoft's **Playwright MCP** through the Anthropic Python SDK's local MCP helpers (`anthropic[mcp]`).
   - Require approval before submitting any form.
   - It's token-heavy (about 100k per task), so only use it when web search and fetch can't do the job.
5. **Madison Metro arrivals.** A free Bus Tracker API key plus GTFS-Realtime: "next 80 bus in 6 minutes" in the morning brief.
6. Later:
   - Notion (official hosted MCP).
   - Spotify (Premium only for development, 5 users).
   - OneDrive/Word through Microsoft Graph. University tenants often block the consent screen, so the fallback is to sync OneDrive to the PC and read the files there.
7. **Don't:** banking. An agent with money access is the worst-case target for prompt injection.

**MCP safety:**
- Official servers only, with pinned versions and a tool allowlist.
- Keep the approval gate for send, delete and share.
- Beware of tool poisoning and of "toxic flows" where an email instructs the agent ([Invariant Labs](https://invariantlabs.ai/blog/mcp-security-notification)).

## 6. Channels: "talk to it anywhere"

| Channel | Verdict |
|---|---|
| **Telegram bot** | **Do first.** Free, and it needs no open port: the PC polls Telegram. Voice notes and files work, and it can be locked to your user ID. |
| **ntfy push** | **Do second.** Free iOS push for proactive alerts: due soon, important email, leave now for the bus. |
| **Slack** (Socket Mode) | Easy, no port needed. Worth it only if you actually live in Slack. |
| **GroupMe** | Bots can read and post in **groups**, not DMs, and need a public webhook (Cloudflare Tunnel or Tailscale Funnel). Later, for a class group. |
| **iMessage** | Needs an always-on **Mac** (BlueBubbles) or a paid relay ($21–100/month). Windows Phone Link has no API. **Skip.** |
| **Instagram DMs** | API access only for business or creator accounts with Meta review; automating a personal account risks a ban. **Skip.** |
| **Snapchat** | No messaging API; automation risks a ban. **Skip.** |
| WhatsApp | The official API is for businesses; unofficial libraries risk a permanent ban, and a malware fork exists. **Skip.** |
| SMS (Twilio) | Works, but needs carrier registration (about $20 setup + $2/month) plus fees. Only if you really want texts. |

- The PC has to be on: Monkey starts at login, and Windows must be set not to sleep (or allowed to wake for scheduled tasks).
- Telegram, Slack and Discord need **no tunnel**. Every channel is restricted to your own account ID.

## 7. Voice: does "100% local (faster-whisper + Kokoro, routed by regex / local model / Haiku)" improve Monkey?

| Piece | Verdict |
|---|---|
| **Kokoro TTS** | **No, not as Monkey's voice.** It has **no voice cloning** (fixed preset voices; [model card](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/README.md)), so it would lose Monkey's voice. Monkey's offline Pocket TTS is already local, clones his voice, and is as fast or faster (0.32× real-time factor, 0.9 s to first audio). At most, Kokoro could replace the robotic Windows SAPI voice as the last fallback. |
| **faster-whisper "flow" / streaming** | **No.** It re-transcribes a growing window to show partial text, which mostly burns CPU for short commands that already end cleanly with Silero VAD. |
| **Better local speech-to-text** | **Yes: NVIDIA Parakeet-TDT-0.6B-v3 (int8) through sherpa-onnx**, which Monkey already ships. About 6.3% word error rate vs 8.6% for Whisper small, and several times faster on CPU ([Open ASR comparisons](https://openwhispr.com/blog/parakeet-vs-whisper-vs-nemotron)). Keep faster-whisper as a fallback. |
| **Regex fast path** | **Yes, and expand it.** Monkey already uses regex for routing. Add instant offline handlers for time, timers, volume, open site, media and "what's next". This takes ~0 ms instead of ~1 s or more, the pattern Home Assistant uses. Keep the patterns strict; anything near-miss goes to the LLM. |
| **Local LLM router** | **Optional.** A 1.7B model could classify in about 0.2–0.5 s (estimate), but it risks misrouting. Simpler: drop the separate classifier call (section 1). |
| **"100% local brain"** | No: you'd lose Claude-quality answers. The ears (speech-to-text) and mouth (TTS) can be fully local; the brain stays Claude. |

**Fish's free tier ends Nov 30.** After that Monkey's main voice becomes the local Pocket TTS clone, so "Make Monkey's voice set" (Settings → Sound) needs to be done **before then**.

## 8. Subagents: the main agent orchestrates, specialists work

Evidence ([Anthropic multi-agent research](https://www.anthropic.com/engineering/multi-agent-research-system)):
- An orchestrator with workers beat a single agent by **90%** on breadth-first research.
- But it costs about **15× the tokens**.
- It's a bad fit when steps depend on each other.

**Design for Monkey:**
- Each subagent is a definition with a role prompt, a model, a tool allowlist and an output format, returning a summary under about 2k tokens.
  - **researcher** (Sonnet lead with 3–5 Haiku workers): internships, products, "compare X vs Y", deep questions. Tools: web search and fetch.
  - **inbox-triager** (Haiku): read-only email ranking and summaries.
  - **planner** (Sonnet): calendar + Canvas + Garmin → plans. *Proposes*; never books.
  - **writer** (Opus): drafts in your voice from memory samples. Drafts only.
  - **tutor** (Sonnet): the study-session and exam-prep skills.
- **Side effects stay with the main agent behind the approval gate.** Subagents never send, book or delete.
- Only spawn subagents for breadth tasks; most voice requests stay single-agent, which keeps them fast and cheap.

## 9. Routines: runs every day before school

- **Morning brief, weekdays.** Windows Task Scheduler runs `Monkey.exe --routine morning`.
  - It's timed **from your first class** (calendar/Canvas): e.g. 60 minutes before, or a fixed time you pick.
  - Turn on "wake the computer" and "run if missed". Laptops may not wake from sleep by design.
  - **Contents:**
    - today's classes and locations;
    - what's due in the next 72 hours, ranked by points;
    - important email;
    - weather;
    - sleep and recovery from Garmin;
    - when to leave for the bus.
  - **Delivery:** an ntfy push / Telegram message, plus it's spoken when you open Monkey.
- **Nightly dream pass:** memory consolidation (section 2), at around 3 AM.
- **Sunday evening:** plan-my-week proposal.
- **Cloud alternative:** a Claude Code scheduled task with your Gmail and Calendar connectors could send the brief even with the PC off. It can't see Canvas or Garmin without extra setup.

---

## Suggested build order (each step ships on its own)

| # | Step | Effort | Why first |
|---|---|---|---|
| 1 | Morning routine (Task Scheduler + brief + ntfy push) | 1 session | Daily value immediately |
| 2 | Memory: episode log + past-conversation search + nightly dream | 1–2 sessions | "Never repeat myself" |
| 3 | Import your ChatGPT profile (prompt doc) into `profile.md` | You, ~20 min | Teaches it who you are |
| 4 | Skills loader + the first 4 school/inbox skills | 1 session | Specialist behavior, cheap tokens |
| 5 | Telegram bot (text + voice notes) | 1 session | Talk to it anywhere |
| 6 | Speed: rules fast path, Parakeet STT, drop the classifier round trip | 1 session | Faster replies |
| 7 | Canvas API (once the token arrives), Drive/Docs, Todoist | 1–2 sessions | More real data |
| 8 | Subagents: researcher + writer | 1 session | Deep work |
| 9 | Playwright browsing (approval-gated), Metro, GroupMe | later | Nice to have |
