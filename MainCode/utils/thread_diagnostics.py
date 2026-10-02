import sys, threading, traceback, time

def dump_threads(only_dummy=True):
    by_ident = {t.ident: t for t in threading.enumerate()}
    frames = sys._current_frames()
    print("="*60, "THREAD SNAPSHOT @", time.strftime('%H:%M:%S'), "="*60)
    for ident, frame in frames.items():
        t = by_ident.get(ident)
        if t is None:
            name = f"<unknown id={ident}>"
        else:
            name = t.name
            if only_dummy and not name.startswith("Dummy-"):
                continue
        print(f"\n--- {name} (id={ident}) daemon={getattr(t,'daemon',None)} ---")
        stack = traceback.format_stack(frame)
        print("".join(stack).rstrip())
    print("="*60)
