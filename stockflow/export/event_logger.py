from pathlib import Path
import csv, datetime

def append_event(base_dir: str, event: dict):
    Path(base_dir).mkdir(parents=True, exist_ok=True)
    day = datetime.datetime.now().strftime("%Y%m%d")
    file = Path(base_dir) / f"flow_{day}.csv"
    new_file = not file.exists()
    with file.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(event.keys()))
        if new_file:
            writer.writeheader()
        writer.writerow(event)
