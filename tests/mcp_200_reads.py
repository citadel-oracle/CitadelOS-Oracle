import time
import os
from src.oracle.tradingview_sync import TradingViewMCPReader

def get_fds():
    try:
        return len(os.listdir('/dev/fd'))
    except:
        return 0

def get_child_and_zombie_count():
    try:
        import psutil
        p = psutil.Process()
        children = p.children(recursive=True)
        zombies = [c for c in children if c.status() == psutil.STATUS_ZOMBIE]
        return len(children), len(zombies)
    except Exception:
        return 0, 0

def main():
    start_children, start_zombies = get_child_and_zombie_count()
    start_fds = get_fds()
    
    reader = TradingViewMCPReader(timeout_seconds=5.0)
    successes = 0
    errors = 0
    error_reasons = {}
    latencies = []
    
    for i in range(200):
        start = time.time()
        try:
            res = reader.read()
            if res.get("success"):
                successes += 1
            else:
                errors += 1
                reason = res.get("error", "unknown_error")
                error_reasons[reason] = error_reasons.get(reason, 0) + 1
        except Exception as e:
            errors += 1
            reason = str(e)
            error_reasons[reason] = error_reasons.get(reason, 0) + 1
        latency = time.time() - start
        latencies.append(latency)
        
    latencies.sort()
    p50 = latencies[len(latencies)//2]
    p95 = latencies[int(len(latencies)*0.95)]
    max_lat = latencies[-1]
    
    mid_children, mid_zombies = get_child_and_zombie_count()
    
    reader.close()
    
    end_children, end_zombies = get_child_and_zombie_count()
    end_fds = get_fds()
    
    print(f"Successes: {successes}")
    print(f"Errors: {errors}")
    print(f"Error reasons: {error_reasons}")
    print(f"P50: {p50*1000:.2f}ms")
    print(f"P95: {p95*1000:.2f}ms")
    print(f"Max: {max_lat*1000:.2f}ms")
    print(f"FDs before: {start_fds}, FDs after: {end_fds}")
    print(f"Children during: {mid_children}, Children after close: {end_children}")
    print(f"Zombies during: {mid_zombies}, Zombies after close: {end_zombies}")

if __name__ == "__main__":
    main()
