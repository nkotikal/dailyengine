import tempfile, pathlib
from datetime import datetime, timedelta
from digest_pipeline import store, memory, tasks

tmp = pathlib.Path(tempfile.mkdtemp())
for a in ["CONFIG_PATH","UPDATES_PATH","STATE_PATH","SCHEDULE_PATH","KOREAN_PATH","TRACKERS_PATH",
          "TRACKER_STATE_PATH","REMINDERS_PATH","MEMORY_PATH","WEEKLY_TASKS_PATH","PROFILE_BASE_PATH"]:
    setattr(store, a, tmp / (a.lower()+".json"))
store.DIR = tmp

# profile base exempt
store.save_profile_base("Nikhil - SWE at AMD, compilers, building Dailyengine.")
print("profile:", store.load_profile_base()[:40])

# add memories with old timestamps to trigger decay/compression
store.add_weekly_task("AMD", "high", subtasks=[{"text":"merge PR"}])
old = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
for i in range(20):
    m = store.add_memory(f"old trivial note {i}", "fact", importance=15)
# force their last_reinforced old
items = store.list_memories()
for m in items:
    m["last_reinforced"] = old
store.replace_memories(items)
store.add_memory("Currently merging the AMD PR", "project", importance=80)

print("before evolve:", len(store.list_memories()))
res = memory.evolve(use_llm=True)
print("evolve result:", res)
print("after evolve:", len(store.list_memories()))
# importance ordering in render
print("render head:\n", memory.render_for_digest(5))

# #3 progress: categories
store.clear_weekly_tasks(False)
store.add_weekly_task("AMD", "high", subtasks=[{"text":"a","done":True},{"text":"b"}])
store.add_weekly_task("Applications", "medium", subtasks=[{"text":"c"}])
print("summary:", tasks.summary())

# korean grade
g = korean = __import__("digest_pipeline.korean", fromlist=["korean"])
res = g.grade_practice(["저는 매일 한국어를 공부해요"], vocab_context="공부하다 (to study)")
print("graded:", res[0]["score"] if res else "none", "-", (res[0]["feedback"][:50] if res else ""))
print("OK")
