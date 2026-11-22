from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path
from .store import LearningStore, DEFAULT_DB

def _parser():
    p = argparse.ArgumentParser(prog="fidelityflow-learn",
        description="Evidence-backed, project-scoped memory for FidelityFlow.")
    p.add_argument("--db", default=str(DEFAULT_DB), help=argparse.SUPPRESS)
    p.add_argument("--root", default=os.getcwd(), help="Project root (defaults to current directory)")
    sub = p.add_subparsers(dest="command", required=True)
    obs = sub.add_parser("observe", help="Record a small fact with evidence")
    obs.add_argument("--key", required=True)
    obs.add_argument("--value", required=True)
    obs.add_argument("--session", default=os.environ.get("CLAUDE_SESSION_ID"), help="Stable session ID; required unless CLAUDE_SESSION_ID is set")
    obs.add_argument("--source", default="manual")
    obs.add_argument("--evidence", required=True)
    obs.add_argument("--min-sessions", type=int, default=2)
    recall = sub.add_parser("recall", help="Print confirmed facts only")
    recall.add_argument("--query", default="")
    recall.add_argument("--limit", type=int, default=12)
    sub.add_parser("candidates", help="List facts awaiting confirmation")
    confirm = sub.add_parser("confirm", help="Manually confirm a candidate")
    confirm.add_argument("--key", required=True)
    confirm.add_argument("--value", required=True)
    retire = sub.add_parser("retire", help="Retire an outdated fact")
    retire.add_argument("--key", required=True)
    retire.add_argument("--value")
    forget = sub.add_parser("forget", help="Delete this project's learned data")
    forget.add_argument("--key")
    sub.add_parser("stats", help="Show local counts")
    return p

def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.command == "observe" and not args.session:
            raise ValueError("--session is required (or set CLAUDE_SESSION_ID); a new random ID per observation would create false independent evidence")
        with LearningStore(args.db, args.root) as store:
            if args.command == "observe":
                result = store.observe(args.key,args.value,args.session,args.source,args.evidence,args.min_sessions)
            elif args.command == "recall":
                result = store.recall(args.query,args.limit)
            elif args.command == "candidates":
                result = store.list_candidates()
            elif args.command == "confirm":
                store.confirm(args.key,args.value); result={"confirmed":True}
            elif args.command == "retire":
                result={"retired":store.retire(args.key,args.value)}
            elif args.command == "forget":
                result={"deleted":store.forget(args.key)}
            else:
                result=store.stats()
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}",file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
