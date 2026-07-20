"""Run one gpt-5.6-sol resume generation at a given reasoning_effort, capture exact
token usage + cost, and SAVE the output for later effort-vs-effort comparison.

Usage:  python3 eval/run_sol_effort.py high      # (later:  ... low)
Artifacts written to eval/artifacts/sol_<effort>.json (+ _usage.json).
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resume_pipeline import core, llm  # noqa: E402
core.load_dotenv()

EFFORT = sys.argv[1] if len(sys.argv) > 1 else "high"
MODEL = "gpt-5.6-sol"
MAX_TOKENS = 16384  # generous so high-effort reasoning is never truncated

profile = json.load(open(ROOT / "samples/profile.sample.json", encoding="utf-8"))
jd = (ROOT / "samples/job_posting.sample.txt").read_text(encoding="utf-8")
system = llm._system_prompt(llm.load_manifesto())
user = llm._build_user_message(
    profile, jd, bold_directive="BOLDING: OFF.", summary_directive="SUMMARY: OFF.")

base = (os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
key = os.environ["OPENAI_API_KEY"]

# Pricing per 1M tokens.
PIN, PCACHE, POUT, PWRITE = 5.00, 0.50, 30.00, 6.25


def post(token_field, include_temp, include_effort):
    body = {"model": MODEL,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            token_field: MAX_TOKENS}
    if include_temp:
        body["temperature"] = 0.3
    if include_effort:
        body["reasoning_effort"] = EFFORT
    req = urllib.request.Request(base + "/chat/completions",
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode())


tf, temp, eff = "max_tokens", True, True
t0 = time.time()
for _ in range(5):
    try:
        payload = post(tf, temp, eff)
        break
    except urllib.error.HTTPError as e:
        d = e.read().decode(errors="replace")
        if "max_completion_tokens" in d and tf == "max_tokens":
            tf = "max_completion_tokens"; continue
        if "temperature" in d and temp:
            temp = False; continue
        if "reasoning_effort" in d and eff:
            print("NOTE: reasoning_effort not accepted on chat/completions; retrying without it.")
            eff = False; continue
        print(f"HTTP {e.code}: {d[:600]}"); raise SystemExit(1)
dt = time.time() - t0

u = payload["usage"]
isl, osl = u["prompt_tokens"], u["completion_tokens"]
ptd = u.get("prompt_tokens_details") or {}
ctd = u.get("completion_tokens_details") or {}
cached = ptd.get("cached_tokens", 0)
cache_write = ptd.get("cache_write_tokens", 0)
reasoning = ctd.get("reasoning_tokens", 0)

# Cost: cache-write tokens billed at write rate, cached at cached rate, rest at input.
in_write = cache_write
in_cached = cached
in_full = isl - in_write - in_cached
cost = (in_full * PIN + in_cached * PCACHE + in_write * PWRITE + osl * POUT) / 1e6

text = payload["choices"][0]["message"]["content"]
prof = llm._parse_json(text)
JD = ["Python", "FastAPI", "AWS", "Kubernetes", "Docker", "Terraform", "Kafka",
      "Snowflake", "PostgreSQL", "Redis", "CI/CD", "Go", "microservice",
      "event pipeline", "infrastructure as code"]
flat = json.dumps({k: v for k, v in prof.items()
                   if k in ("skills", "experience", "projects")}).lower()
cov = [k for k in JD if k.lower() in flat]

art = ROOT / "eval" / "artifacts"
art.mkdir(parents=True, exist_ok=True)
json.dump(prof, open(art / f"sol_{EFFORT}.json", "w"), indent=2, ensure_ascii=False)
usage = {"effort": EFFORT, "latency_s": round(dt, 1), "isl": isl, "osl": osl,
         "cached": cached, "cache_write": cache_write, "reasoning_tokens": reasoning,
         "cost_usd": round(cost, 5), "ats_covered": len(cov), "ats_total": len(JD),
         "ats_missing": [k for k in JD if k not in cov], "raw_usage": u}
json.dump(usage, open(art / f"sol_{EFFORT}_usage.json", "w"), indent=2)

print(f"\n=== gpt-5.6-sol  reasoning_effort={EFFORT} (applied={eff}) ===")
print(f"latency={dt:.1f}s")
print(f"ISL={isl} (cached={cached}, cache_write={cache_write})  OSL={osl} (reasoning={reasoning})")
print(f"COST = ${cost:.5f}  ({cost*100:.3f} cents)")
print(f"ATS coverage = {len(cov)}/{len(JD)}  missing={usage['ats_missing']}")
print(f"summary: {(prof.get('summary') or '')[:280]}")
print(f"\nsaved: eval/artifacts/sol_{EFFORT}.json  +  sol_{EFFORT}_usage.json")
