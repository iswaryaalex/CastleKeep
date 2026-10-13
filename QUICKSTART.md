# Sanctum – Workshop Quickstart

## 1. Start the app

```powershell
cd C:\Users\<you>\local-ai-workshop\Sanctum
python run.py
```

Leave this terminal open. You'll see the URLs printed once it's ready.

---

## 2. Phase 1 — prove the sandbox by hand

Open `http://127.0.0.1:7701/phase1` in your browser.

Open a **second PowerShell terminal** and follow the steps on screen in order:

1. **Build the lab** — creates `C:\SanctumLab` with sample files and a poisoned document
2. **Probe the host** — asks what this machine can actually enforce
3. **Validate without running** — dry-run a config, nothing spawns
4. **Spawn one for real** — first real sandbox
5. **Grant a path, then reach past it** — watch the policy block a read
6. **Injection, unsandboxed** — the secret prints; nothing stopped it
7. **Injection, inside the sandbox** — same attack, key never prints
8. **Network** — egress denied, then allowed *(if time)*

When all steps are done, come back to the browser.

---

## 3. Phase 2 — put an agent in front of the sandbox

Click **Phase 2 →** in the browser (or go to `http://127.0.0.1:7701/`).

- **First time:** click **Set up →** to name your agent and configure it
- **Returning:** click **Open →** to go straight to the app

Chat with your agent. Every tool call runs in the same sandbox you just proved by hand.

---

## Stop

`Ctrl-C` in the run.py terminal.
