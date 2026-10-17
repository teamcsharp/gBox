"""Use the installed Hermes external-drain API; status is the default.

No restart, schedule edits, task-mode writes, claim edits or cancellations.
The API's read-then-clear is not an atomic compare-and-swap. Run under the
deployment lock and preserve a marker changed by another operator.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def begin(api, home, owner, receipt):
    if not owner or not owner.startswith('gbox-deploy:'):
        raise ValueError('Use a unique gbox-deploy:<commit>:<nonce> owner')
    if api.read_drain_request(home=home) is not None:
        raise ValueError('An existing drain marker must be respected; no change made')
    # Reserve the evidence path before requesting a drain. A reused receipt may
    # name another operator's maintenance and must never be overwritten.
    with Path(receipt).open('x', encoding='utf-8') as stream:
        payload = api.write_drain_request(home=home, principal=owner, suppress_notification=True)
        json.dump({'owner': owner, 'home': str(home.resolve()), 'marker': payload}, stream, indent=2)
        stream.write('\n'); stream.flush()
        import os
        os.fsync(stream.fileno())
    return {'requested': True, 'marker': payload, 'max_age_s': api.DRAIN_REQUEST_MAX_AGE_SECONDS,
            'receipt': str(receipt), 'boundary': 'Request written; wait for the live gateway acknowledgment.'}


def release(api, home, owner, receipt):
    saved = json.loads(Path(receipt).read_text(encoding='utf-8'))
    if (saved.get('owner') != owner or saved.get('home') != str(home.resolve())
            or not isinstance(saved.get('marker'), dict) or saved['marker'].get('principal') != owner):
        raise ValueError('Receipt does not identify this owner and Hermes home')
    current = api.read_drain_request(home=home)
    if current is None:
        return {'released': False, 'already_absent': True}
    if current != saved['marker']:
        raise ValueError('Drain marker changed; preserve the other maintenance/operator request')
    # Installed API has no ownership-CAS option. This is an ordinary serialized
    # maintenance release after an exact readback, not a claim of atomic CAS.
    return {'released': api.clear_drain_request(home=home), 'owner': owner}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--begin', action='store_true')
    action.add_argument('--release', action='store_true')
    parser.add_argument('--home', type=Path, default=Path.home()/'.hermes')
    parser.add_argument('--runtime', type=Path)
    parser.add_argument('--owner', required=True)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    if (args.begin or args.release) and args.receipt is None:
        parser.error('--receipt is required for begin/release')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(args.runtime or args.home/'hermes-agent'))
    import hermes_bootstrap  # Load the installed launcher's managed dependency closure.
    from gateway import drain_control
    if args.begin:
        result = begin(drain_control, args.home, args.owner, args.receipt)
    elif args.release:
        result = release(drain_control, args.home, args.owner, args.receipt)
    else:
        from gbox.hermes_drain import acknowledgment
        result = acknowledgment(args.home, args.owner)
        result['marker'] = drain_control.read_drain_request(home=args.home)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
