# What should power Monkey's brain? (researched 2026-11-18)

## Short answer
- **Keep the Anthropic API key.** It's the only option that is fully allowed by the terms, fast enough for voice, and supports all of Monkey's tools as-is: web search, memory, email, Canvas, Garmin.
- **Use the "Saver" brain profile** (Settings → Brain & budget). It sends heavy work to Sonnet and saves Opus for things you say are important. That's **about $20–25 a month** at heavy use, instead of about $40–50.
- **Your ChatGPT subscription can help, but not through OpenClaw.** Use OpenAI's official **Sign in with ChatGPT**, built directly into Monkey; that's a possible next step. OpenClaw works, but it's a heavy extra program with a bad security record, and running Monkey through it is a grey area.
- **Don't use your Claude Pro/Max login inside Monkey.** Anthropic's terms forbid custom apps from sending requests through subscription credentials, and Anthropic has enforced this since early 2026.

## The math
Assumed usage per day:
- **80 light turns:** about 7k input tokens, 6k of them cached; 150 output tokens.
- **15 medium turns:** 10k input; 400 output; 30% use one web search.
- **5 heavy turns:** 40k input; 2.5k output; 2 web searches each.

Prices per 1M tokens:

| Model | Input | Cache read | Output |
|---|---|---|---|
| Haiku 5.5 | $0.10 | $0.01 | $0.50 |
| Sonnet 5.5 | $2 | $0.10 | $10 |
| Opus 5.5 | $4 | $0.20 | $20 |

Web search costs $0.01 per search.

| Router setup (light / medium / heavy) | $/month |
|---|---|
| Haiku / Sonnet / Opus ("Best", the default) | **$39–51** |
| Haiku / Sonnet / Sonnet, Opus only when important ("Saver") | **≈$20–28** |
| Haiku for everything | $6–8 (weak at research and writing) |
| Haiku, heavy work on your ChatGPT plan through Sign in with ChatGPT | $2–4 (needs that integration) |

Heavy turns dominate the cost: 5 Opus research or drafting turns a day cost about $31 a month on their own. The ranges cover warm vs. cold prompt cache. Monkey now uses a 1-hour cache on its fixed instructions, which pushes toward the low end. Your real spend shows in Settings, and the monthly budget cap applies.

## Options compared

| Option | Extra $/mo | Allowed by the terms? | Voice delay | Tools | Verdict |
|---|---|---|---|---|---|
| **Anthropic API key** (current) | $20–51 depending on profile | ✅ Yes | Best: Haiku under 1 s, Sonnet/Opus 2–6 s | All of Monkey's tools as-is | **Use this** |
| Claude Pro/Max via `claude -p` or the Agent SDK | $20+ flat | ⚠️ Your own unmodified Claude Code is fine, but a custom app sending requests through your plan login is **not** allowed | Slow: it starts the whole Claude Code program each time | Tools would have to be rewritten | No |
| **ChatGPT plan via OpenClaw** | $0 extra | ⚠️ Grey area: OpenAI says plan usage is "only for the application they connected" | 2–6 s plus OpenClaw's overhead | Wrapped inside OpenClaw's own agent | No: security history (a 1-click remote-code bug, malicious add-ons on its marketplace) and limits shared with your normal ChatGPT use |
| ChatGPT plan via **Sign in with ChatGPT** inside Monkey | $0 extra (Plus/Pro) | ✅ Official; open-source and local personal apps are listed as eligible | ~1–2 s | Good; some OpenAI-hosted tools unavailable | **Best way to use your ChatGPT plan**, as an add-on for heavy turns |
| Codex CLI with a ChatGPT login | $0 extra | ✅ It's OpenAI's own tool | 3–10 s | Built for coding agents | No |
| OpenRouter | List prices + 5.5% fee on credits | ✅ | Varies by model | Same as the underlying model | No real savings; free models may log your prompts |
| Gemini API | ~$8 paid Flash-Lite; possibly $0 with the student Google AI Pro offer (claim by 2026-12-31) | ✅ with an API key | Fast | Would need rewriting | Possible cheap backup |
| GitHub Copilot Student | – | ⚠️ | – | Automatic model choice only, ~$2/mo of credits | No |
| Local Ollama model on the XPS | $0 | ✅ | Several seconds | Weak | Offline fallback only |

## Sources
- [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- [Claude Code legal & compliance](https://code.claude.com/docs/en/legal-and-compliance) (subscription login vs. API key)
- [The Register: Anthropic clarifies third-party access ban (2026-02-20)](https://www.theregister.com/2026/02/20/anthropic_clarifies_ban_third_party_claude_access)
- [TechCrunch: OpenClaw and Claude subscriptions (2026-04-04)](https://techcrunch.com/2026/04/04/anthropic-says-claude-code-subscribers-will-need-to-pay-extra-for-openclaw-support/)
- [Sign in with ChatGPT cookbook](https://developers.openai.com/cookbook/articles/sign-in-with-chatgpt)
- [Sign in with ChatGPT terms](https://openai.com/policies/sign-in-with-chatgpt-terms/)
- [The New Stack on Sign in with ChatGPT](https://thenewstack.io/sign-in-with-chatgpt/)
- [Codex pricing and limits](https://developers.openai.com/codex/pricing)
- [OpenClaw security overview](https://adversa.ai/blog/openclaw-security-101-vulnerabilities-hardening-2026/)
- [OpenRouter pricing](https://openrouter.ai/pricing)
- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Google AI student offer](https://blog.google/innovation-and-ai/products/gemini-app/student-offer-google-ai/)
- [Copilot student changes](https://github.com/orgs/community/discussions/189268)
