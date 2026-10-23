#!/usr/bin/env python3
"""Evaluate native OpenCode V2 skill loads, not textual skill mentions.

Local adaptation of the Anthropic skill-creator; see OPENCODE_PORT.md.
"""

import argparse
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from scripts.opencode_runtime import OpenCodeError, cancel_run, isolated_workspace, run_opencode
from scripts.utils import parse_skill_md


def find_project_root() -> Path:
    """Compatibility helper; evals never write to or discover this project."""
    return Path.cwd()


def run_single_query(
    query: str,
    skill_name: str,
    skill_description: str,
    timeout: int,
    project_root: str,
    model: str | None = None,
    cancel_event: threading.Event | None = None,
) -> bool:
    """Return an exact completed native skill load, or raise on an invalid run.

project_root remains accepted for callers, but is deliberately not used as cwd.
Only the description and ID are under test, not skill-body task execution.
"""
    try:
        if cancel_event is not None and cancel_event.is_set():
            raise OpenCodeError('OpenCode run cancelled')
        with isolated_workspace(skill_name, skill_description) as (workspace, env):
            events = run_opencode(query, model, timeout, workspace, env, cancel_event=cancel_event)
        return any(
            event.get('type') == 'tool_use'
            and (part := event.get('part', {})).get('tool') == 'skill'
            and (state := part.get('state', {})).get('status') == 'completed'
            and state.get('input', {}).get('id') == skill_name
            for event in events
        )
    except BaseException:
        # Signal before the pool can dequeue this worker's next trial, not only
        # when the main thread eventually observes the failed future.
        cancel_run(cancel_event)
        raise


def run_eval(
    eval_set: list[dict],
    skill_name: str,
    description: str,
    num_workers: int,
    timeout: int,
    project_root: Path,
    runs_per_query: int = 1,
    trigger_threshold: float = 0.5,
    model: str | None = None,
) -> dict:
    """Evaluate concurrently; infrastructure failures abort instead of scoring."""
    if not eval_set or num_workers < 1 or runs_per_query < 1 or timeout <= 0:
        raise ValueError('Nonempty evals and positive workers, runs, timeout are required')
    if not 0 < trigger_threshold <= 1:
        raise ValueError('trigger_threshold must be in (0, 1]')
    queries = [item['query'] for item in eval_set]
    if len(set(queries)) != len(queries):
        raise ValueError('Eval queries must be unique (including across train/test)')
    if any(not isinstance(q, str) or not q.strip() for q in queries):
        raise ValueError('Queries must be nonempty strings')
    if any(type(item.get('should_trigger')) is not bool for item in eval_set):
        raise ValueError('should_trigger must be boolean')
    observations = [[] for _ in eval_set]
    cancel_event = threading.Event()
    executor = ThreadPoolExecutor(max_workers=num_workers)
    futures = {}
    try:
        for idx, item in enumerate(eval_set):
            for _ in range(runs_per_query):
                if cancel_event.is_set():
                    raise OpenCodeError('A trial failed; evaluation cancelled')
                future = executor.submit(run_single_query, item['query'], skill_name, description,
                                         timeout, str(project_root), model, cancel_event=cancel_event)
                futures[future] = idx
        for future in as_completed(futures):
            observations[futures[future]].append(future.result())
    except BaseException as exc:
        cancel_run(cancel_event)
        for pending in futures:
            pending.cancel()
        if isinstance(exc, Exception):
            raise OpenCodeError(f'Evaluation aborted; no valid score: {exc}') from exc
        raise
    finally:
        # On failure the event is already set: wait only for active cleanup,
        # never for queued trials to start additional model requests.
        executor.shutdown(wait=True, cancel_futures=True)
    results = []
    for item, triggers in zip(eval_set, observations):
        rate = sum(triggers) / len(triggers)
        results.append({
            **item, 'trigger_rate': rate, 'triggers': sum(triggers), 'runs': len(triggers),
            'pass': (rate >= trigger_threshold) == item['should_trigger'],
        })
    passed = sum(r['pass'] for r in results)
    return {
        'skill_name': skill_name, 'description': description, 'results': results,
        'summary': {'total': len(results), 'passed': passed, 'failed': len(results) - passed},
    }


def main():
    parser = argparse.ArgumentParser(description='Evaluate OpenCode V2 skill description discovery')
    parser.add_argument('--eval-set', required=True)
    parser.add_argument('--skill-path', required=True)
    parser.add_argument('--description')
    parser.add_argument('--num-workers', type=int, default=10)
    parser.add_argument('--timeout', type=int, default=120)
    parser.add_argument('--runs-per-query', type=int, default=3)
    parser.add_argument('--trigger-threshold', type=float, default=0.5)
    parser.add_argument('--model', required=True, help='provider/model#variant (variant optional)')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    name, description, _ = parse_skill_md(Path(args.skill_path))
    output = run_eval(json.loads(Path(args.eval_set).read_text()), name,
                      args.description if args.description is not None else description,
                      args.num_workers, args.timeout, find_project_root(),
                      args.runs_per_query, args.trigger_threshold, args.model)
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
