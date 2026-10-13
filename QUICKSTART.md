# Sanctum – Workshop Quickstart

---

## Step 1 — Start the app

Open a PowerShell terminal and run:

```powershell
cd C:\Users\<you>\local-ai-workshop\Sanctum
python run.py
```

Leave this terminal open and running the whole time.

---

## Step 2 — Open Phase 1 in your browser

Go to: **`http://127.0.0.1:7701/phase1`**

This page shows 8 numbered steps with the exact commands for your machine.

---

## Step 3 — Open a second terminal and follow Phase 1

Open a **second PowerShell terminal**:

```powershell
cd C:\Users\<you>\local-ai-workshop\Sanctum
```

Now go through each step on the browser page, copying each command into this terminal and running it before moving to the next. The page explains what each step proves.

Steps 1–8 in order:

1. Build the lab
2. Probe the host
3. Validate without running
4. First real sandbox
5. Grant a path, then reach past it (three variants)
6. Injection — unsandboxed *(the secret prints)*
7. Injection — sandboxed *(the secret never prints)*
8. Network *(if time)*

When you have finished all 8 steps, close the Phase 1 page.

---

## Step 4 — Move to Phase 2

Go to: **`http://127.0.0.1:7701/`**

**First time here:** click **Set up →**, name your agent, then come back and click **Open →**

**Already set up:** click **Open →**

You are now in the app. Try one of the starter tasks listed in the chat.

---

## To stop

Press `Ctrl-C` in the first terminal.
