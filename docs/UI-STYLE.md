# UI style: jungle theme with Supercell/Fortnite-style "game UI" patterns

*Researched 2026-11-18.*

- **Generic patterns only.** No logos, icons, art, sounds or proprietary fonts are copied.
- **The numbers are our proposals,** tuned for a WebView. They aren't measurements from the games.
- **Sources** were checked through search summaries. Page fetches were blocked in the research session.

## Tokens
```css
--ink:#14240F;                       /* dark green-black outline instead of pure black */
--banana:#FFD43B; --banana-lip:#C98F00;   /* primary action */
--leaf:#3CC24A;   --leaf-lip:#1E7A2E;     /* secondary action */
--ease-pop:cubic-bezier(.34,1.56,.64,1);  /* overshoot */
```
**Color roles:** Clash Royale uses yellow for the most important action and green for secondary ones ([The Rookies](https://discover.therookies.co/2020/02/24/game-design-ux-best-practices-detailed-breakdown-of-clash-royale/)). Here that becomes banana for primary actions and leaf green for secondary ones.

## Buttons: chunky, outlined, with a pressable "lip"
- 3px ink outline, 12–16px radius, at least 48px tall.
- Two-tone gradient with a hard top highlight.
- A solid 6px bottom "lip" shadow. On press the button moves down with `transform`; the shadow isn't animated ([Comeau](https://www.joshwcomeau.com/animation/3d-button/), [Schier](https://schier.co/blog/clicky-3d-buttons-with-css)).
- Sizes: S 36px, M 48px, L 64px.

## Typography
- **The games' own fonts are proprietary:**
  - Clash Royale: "Supercell-Magic", based on Comicraft's You Blockhead ([Comicraft](https://comicraft.com/?p=1082)).
  - Fortnite: Burbank Big Condensed, a commercial font ([Fonts in Use](https://www.fontsinuse.com/uses/54645/fortnite)).
- **Open-license look-alikes:**
  - **Lilita One** (SIL OFL 1.1), used here for display text ([Fontsource](https://fontsource.org/fonts/lilita-one/about)).
  - Also suitable: Luckiest Guy (Apache 2.0), Bungee (OFL), and Anton or Teko (OFL) for condensed headers.
- **Display text:** white or banana yellow, a thick ink stroke drawn behind the fill (`-webkit-text-stroke` + `paint-order: stroke fill`) and a hard drop shadow.
- **Fallback:** a multi-direction `text-shadow` outline where `paint-order` isn't supported ([MDN](https://developer.mozilla.org/ja/docs/Web/CSS/paint-order)).
- **Body text** stays in a plain sans.

## Panels, cards, rarity
- Panels have an ink border, an 18px radius, an inner top highlight, a 6px drop "lip", and a header strip in the accent color.
- **How the games do rarity:**
  - Clash Royale: Common, Rare, Epic, Legendary, Champion ([Fandom](https://clashroyale.fandom.com/wiki/Cards)).
  - Brawl Stars: Rare through Legendary ([Supercell](https://support.supercell.com/brawl-stars/en/articles/brawler-rarities-3.html)).
  - Fortnite: grey, green, blue, purple, gold ([Twinfinite](https://twinfinite.net/guides/fortnite-gun-weapon-colors-mean-what/)).
- **Our 4 tiers** (assignment priority) always come with a text label, never color alone:

| Tier | Fill | Frame | Glow |
|---|---|---|---|
| Legendary (critical) | `#FFE36E → #FFB300 → #FF7A00` | `#A64B00` | `0 0 18px #FFC94099` + shine sweep |
| Epic (high) | `#D58CFF → #8E2DE2` | `#55168F` | `0 0 14px #C266FF99` |
| Rare (normal) | `#6EC6FF → #1E88E5` | `#0D4E9A` | `0 0 12px #6EC6FF80` |
| Common (low) | `#C9D1D9 → #8E99A4` | `#5C6670` | none |

## Motion ("juice")
- **Background:** layer easing, flashes, particles and floating text, but sparingly. This follows GDC's "Juice It or Lose It" ([GDC Vault](https://gdcvault.com/play/1016789/Juice-It-or-Lose)) and its counterpoint talk ([GDC Vault](https://gdcvault.com/play/1020861/Don-t-Juice-It-or)).
- **Durations:**
  - Press: 80–100ms.
  - Panel in: 320–420ms with `--ease-pop`.
  - Reward pop: 500ms, scaling 0.6 → 1.12 → 0.96 → 1.
  - Count-up: 800–1200ms.
  - Stagger list items by 40–60ms.

## Layout
- Icon-first, big outlined numbers (28–48px) ([Pixune](https://pixune.com/blog/best-examples-mobile-game-ui-design/)).
- Skewed "ribbon" headers as an accent only. Fortnite itself moved away from slanted buttons in 2023 ([WePC](https://www.wepc.com/news/fortnite-new-interface/)).
- Progress bars: ink border, dark inset track, striped green fill.

## Accessibility
- **Outlined text:** WCAG counts the outline as the text color, so it must contrast at least 4.5:1, or 3:1 for large text ([WebAIM](https://webaim.org/articles/contrast/)).
- **Reduced motion:** respect `prefers-reduced-motion` (WCAG 2.3.3, [W3C](https://w3.org/WAI/WCAG21/Understanding/animation-from-interactions)). Replace bounce, shine and confetti with short fades.
- **Hit targets:** 44–48px or larger.
