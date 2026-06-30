"""Daily Digest engine.

A self-contained feature, isolated from the resume pipeline: you feed it info
about yourself, your goals, and your tasks, log updates as they happen, and it
emails you a compartmentalized morning digest of what's new and what to do today.

Modules:
  store        - JSON persistence (config, updates, run state) under data/digest/.
  llm          - small Anthropic-compatible gateway client + digest composer.
  email_send   - SMTP delivery via the Python standard library.
  digest       - orchestration: build/render/send + "is it due?" logic.
  scheduler    - background thread that sends the digest each morning.
"""
