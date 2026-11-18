"""Print the model-policy table as markdown (used to keep docs/MODEL-POLICY.md in sync with model_policy.json).

    python -m tools.model_policy.report   (from the repo root; or set PYTHONPATH=.)
"""
from monkey.brain.policy import ModelPolicy


def money(v: float) -> str:
    return f"${v:.4f}" if v < 0.01 else f"${v:.3f}" if v < 1 else f"${v:.2f}"


def main() -> None:
    p = ModelPolicy()
    print("| Task | ⚡ Quick (min) | **Auto (default)** | ★ Important (max) | Auto cost / use | First words | Auto / month |")
    print("|---|---|---|---|---|---|---|")
    for r in p.table():
        print(f"| {r['label']} | {r['min']['label']} ({money(r['min']['usd'])}) | **{r['default']['label']}** | "
              f"{r['max']['label']} ({money(r['max']['usd'])}) | {money(r['default']['usd'])} | "
              f"{r['default']['first_words_s']}s | {money(r['default']['per_month_usd'])} |")
    print()
    print(f"Monthly totals (heavy use): Auto **${p.monthly_total():.2f}**, all Quick ${p.monthly_total('min'):.2f}, "
          f"all Important ${p.monthly_total('max'):.2f}.")


if __name__ == "__main__":
    main()
