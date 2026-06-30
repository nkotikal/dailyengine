import traceback
from resume_pipeline.core import load_dotenv
load_dotenv()
from digest_pipeline import digest, store

# add a dated reminder and an undated one
try:
    store.add_reminder("Submit AMD PR", due="2026-06-30", priority="high")
    store.add_reminder("Renew LinkedIn premium", due="", priority="low")
    cfg = dict(store.load_config())
    cfg.update({"offline": True, "include_trackers": False, "include_calendar": False})
    built = digest.build_digest(cfg)
    print("sections:", [s["title"] for s in built["data"]["sections"]])
    for s in built["data"]["sections"]:
        if "Reminder" in s["title"] or "Upcoming" in s["title"]:
            for it in s["items"]:
                print("   ", it["priority"], "-", it["text"])
finally:
    # cleanup the test reminders
    for r in store.list_reminders():
        if r["text"] in ("Submit AMD PR", "Renew LinkedIn premium"):
            store.delete_reminder(r["id"])
    print("cleaned test reminders")
