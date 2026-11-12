"""Compare worker assignment between the launch that worked and the ones that queue.

If the successful launch carried a `require_worker` and the stuck ones are `None`, the dispatcher is the difference - and the fix is to name the worker. If both are
`None`, the queue itself is stuck and a restart is the honest answer.
"""
import json
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()


def call(path, timeout=25):
    request = urllib.request.Request(
        "http://127.0.0.1:18765" + path,
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"})
    return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")


if __name__ == "__main__":
    jobs = call("/api/jobs?limit=12")
    jobs = jobs if isinstance(jobs, list) else (jobs.get("items") or [])
    print(f"{'time':9s} {'tool':13s} {'state':11s} {'require_worker':20s} {'id'}")
    for job in jobs[:12]:
        stamp = time.strftime("%H:%M:%S", time.localtime(job.get("created") or 0))
        print(f"{stamp:9s} {str(job.get('tool'))[:13]:13s} {str(job.get('state'))[:11]:11s} "
              f"{str(job.get('require_worker'))[:20]:20s} {job.get('id')}")

    print("\nqueued/running now:")
    active = call("/api/jobs?state=queued,running")
    active = active if isinstance(active, list) else (active.get("items") or [])
    for job in active:
        print(f"  {job.get('id')} {job.get('tool')} {job.get('state')} "
              f"worker={job.get('require_worker')} input_keys={sorted((job.get('input') or {}))[:6]}")
