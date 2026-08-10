"""Watch bootstrap progress - run: python watch_progress.py"""
import sys, time, requests
sys.stdout.reconfigure(encoding="utf-8")

print("Watching bootstrap progress... Ctrl+C to stop.\n")
last_checked = -1
while True:
    try:
        r = requests.get("http://localhost:5000/api/status", timeout=15)
        d = r.json()
        total = d.get("total_stocks", 0)
        lr = d.get("last_refresh")
        checked = 0
        if lr:
            status   = lr["status"]
            checked  = lr["checked"]
            updated  = lr["updated"]
            failed   = lr["failed"]
            started  = lr.get("started_at", "?")
            finished = lr.get("finished_at", "—")
            pct = f"{checked/total*100:.1f}%" if total else "?"
            line = (f"[{status.upper():10}]  DB stocks: {total:>5}  "
                    f"Checked: {checked:>5}/{total}  ({pct})  "
                    f"Updated: {updated}  Failed: {failed}")
            if status == "done":
                print(line)
                print(f"\nDone! Started: {started}  Finished: {finished}")
                break
        else:
            line = f"[LOADING...]  DB stocks: {total:>5}  (waiting for refresh to start)"

        if checked != last_checked:
            print(line)
            last_checked = checked

        time.sleep(3)
    except KeyboardInterrupt:
        print("\nStopped.")
        break
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(5)
