"""Small, bounded resource samples for background admission; never generate load."""
from __future__ import annotations

import csv
import io
import math
import os
import shutil
import subprocess
import threading
import time


def percent(value):
    try:
        value = float(value)
        return round(value, 1) if math.isfinite(value) and 0 <= value <= 100 else None
    except (ValueError, TypeError):
        return None


def memory_mb(value):
    # Unified-memory GPUs (GB10) report [N/A] for dedicated VRAM. Preserve
    # their valid utilization sample instead of discarding the entire GPU.
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, TypeError):
        return None


class Sampler:
    def __init__(self, cache=None):
        self.lock = threading.Lock()
        self.value = {}
        self.primed = False
        self.cache = cache

    def snapshot(self):
        with self.lock:
            return dict(self.value)

    def sample(self):
        result = {'sampled_at': time.time(), 'cpu_percent': None, 'memory_percent': None,
                  'memory_available_bytes': None, 'gpus': [], 'gpu_status': 'unavailable'}
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=None)
            memory = psutil.virtual_memory()
            # psutil's first nonblocking reading is not a measurement interval.
            if self.primed:
                result['cpu_percent'] = percent(cpu)
            self.primed = True
            result.update(memory_percent=percent(memory.percent), memory_available_bytes=memory.available,
                          memory_total_bytes=getattr(memory, 'total', None))
        except (ImportError, OSError, RuntimeError) as error:
            result['cpu_error'] = type(error).__name__
        if self.cache:
            try:
                from pathlib import Path
                path = Path(self.cache)
                while not path.exists() and path != path.parent: path = path.parent
                result['cache_free_bytes'] = shutil.disk_usage(path).free
            except OSError:
                result['cache_free_bytes'] = None
        binary = shutil.which('nvidia-smi')
        if binary:
            try:
                command = [binary, '--query-gpu=uuid,name,utilization.gpu,memory.used,memory.total',
                           '--format=csv,noheader,nounits']
                reply = subprocess.run(command, capture_output=True, text=True, timeout=2, check=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                for row in csv.reader(io.StringIO(reply.stdout)):
                    if len(row) != 5:
                        raise ValueError('Unexpected GPU sample')
                    uid, name, load, used, total = (s.strip() for s in row)
                    result['gpus'].append({'id': uid, 'name': name, 'utilization_percent': percent(load),
                                           'memory_used_mb': memory_mb(used), 'memory_total_mb': memory_mb(total)})
                result['gpu_status'] = 'measured' if result['gpus'] else 'no_devices'
            except (subprocess.SubprocessError, OSError, ValueError) as error:
                result['gpu_error'] = type(error).__name__
        with self.lock:
            self.value = result
        return self.snapshot()


def run(stop, sampler, interval=10):
    while not stop.is_set():
        sampler.sample()
        stop.wait(interval)
