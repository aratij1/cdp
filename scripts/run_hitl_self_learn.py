#!/usr/bin/env python3
"""HITL self-learn CLI: mine patterns → memory → FA-safe retry plan.

Never auto-accepts field values. Learning is pattern → playbook only.
STP flips must go through existing reprocess runners with FA=0 gates.

Examples:
  python3 scripts/run_hitl_self_learn.py mine \\
    --run-dir evaluation_results/hackathon5000_sample_2000_v1

  python3 scripts/run_hitl_self_learn.py plan \\
    --run-dir evaluation_results/hackathon5000_sample_2000_v1 \\
    --memory-dir evaluation_results/hitl_self_learn_memory

  python3 scripts/run_hitl_self_learn.py record-flip \\
    --memory-dir evaluation_results/hitl_self_learn_memory \\
    --pattern-id abcd1234 --claim-id 'Group A__M0472JCZ.013'
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.hitl_self_learn.memory import MemoryStore, apply_events
from packages.hitl_self_learn.mine import mine_run, summarize_events
from packages.hitl_self_learn.plan import plan_retries, write_plan


def _default_memory(run_dir: Path) -> Path:
    return ROOT / "evaluation_results" / "hitl_self_learn_memory"


def cmd_mine(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    memory_dir = Path(args.memory_dir).resolve() if args.memory_dir else _default_memory(run_dir)
    out_dir = (
        Path(args.out_dir).resolve()
        if args.out_dir
        else run_dir / "hitl_self_learn"
    )
    events = mine_run(run_dir, run_id=args.run_id or run_dir.name)
    store = MemoryStore(memory_dir)
    apply_events(store, events)
    items = plan_retries(
        events,
        store,
        include_keep_hitl=bool(args.include_keep_hitl),
        include_active_learning=not bool(args.skip_active_learning),
    )
    paths = write_plan(
        items,
        out_dir,
        meta={
            "run_dir": str(run_dir),
            "memory_dir": str(memory_dir),
            "mine": summarize_events(events),
            "honesty": (
                "pattern→playbook only; never auto-accept values; "
                "execute retries via reprocess_* scripts with FA=0 gate"
            ),
        },
    )
    report = {
        "events": len(events),
        "patterns_in_memory": len(store.all_patterns()),
        "plan_items": len(items),
        "memory_index": str(store.index_path),
        "outputs": {k: str(v) for k, v in paths.items()},
        "mine_summary": summarize_events(events),
        "plan_by_remediation": json.loads(paths["summary"].read_text())["by_remediation"],
    }
    print(json.dumps(report, indent=2))
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    """Re-mine events and emit plan using existing memory (refresh playbooks)."""
    return cmd_mine(args)


def cmd_show(args: argparse.Namespace) -> int:
    memory_dir = Path(args.memory_dir).resolve()
    store = MemoryStore(memory_dir)
    rows = [r.to_dict() for r in store.all_patterns()]
    if args.top:
        rows = rows[: int(args.top)]
    print(json.dumps({"pattern_count": len(store.all_patterns()), "patterns": rows}, indent=2))
    return 0


def cmd_record_flip(args: argparse.Namespace) -> int:
    store = MemoryStore(Path(args.memory_dir).resolve())
    store.record_stp_flip(args.pattern_id, args.claim_id)
    rec = store.get(args.pattern_id)
    print(
        json.dumps(
            {
                "pattern_id": args.pattern_id,
                "claim_id": args.claim_id,
                "stp_flip_count": rec.stp_flip_count if rec else None,
                "found": rec is not None,
            },
            indent=2,
        )
    )
    return 0 if rec is not None else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    mine_p = sub.add_parser("mine", help="Mine HITLs, update memory, write retry plan")
    mine_p.add_argument("--run-dir", required=True, help="Cascade run directory with results.jsonl")
    mine_p.add_argument("--memory-dir", default=None, help="Pattern memory root")
    mine_p.add_argument("--out-dir", default=None, help="Plan output directory")
    mine_p.add_argument("--run-id", default=None)
    mine_p.add_argument("--include-keep-hitl", action="store_true")
    mine_p.add_argument("--skip-active-learning", action="store_true")
    mine_p.set_defaults(func=cmd_mine)

    plan_p = sub.add_parser("plan", help="Same as mine (refresh plan from ledger + memory)")
    plan_p.add_argument("--run-dir", required=True)
    plan_p.add_argument("--memory-dir", default=None)
    plan_p.add_argument("--out-dir", default=None)
    plan_p.add_argument("--run-id", default=None)
    plan_p.add_argument("--include-keep-hitl", action="store_true")
    plan_p.add_argument("--skip-active-learning", action="store_true")
    plan_p.set_defaults(func=cmd_plan)

    show_p = sub.add_parser("show", help="Print pattern memory")
    show_p.add_argument(
        "--memory-dir",
        default=str(ROOT / "evaluation_results" / "hitl_self_learn_memory"),
    )
    show_p.add_argument("--top", type=int, default=0, help="Limit rows (0=all)")
    show_p.set_defaults(func=cmd_show)

    flip_p = sub.add_parser("record-flip", help="Credit pattern after HITL→TRUE_STP")
    flip_p.add_argument(
        "--memory-dir",
        default=str(ROOT / "evaluation_results" / "hitl_self_learn_memory"),
    )
    flip_p.add_argument("--pattern-id", required=True)
    flip_p.add_argument("--claim-id", required=True)
    flip_p.set_defaults(func=cmd_record_flip)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
