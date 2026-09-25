---
title: "Session 02 — Operational Literacy: the Machine Behind the Cloud"
session: 02
source: "oriolrius/esade-devops:backlog/docs/doc-4 - Session-02-Operational-Literacy.md"
source_revision: 4a391ec3847b48d414a2ff3b35a9092eb319984d
---

# Session 02 — Operational Literacy: the Machine Behind the Cloud

Session 02 solves the problem that "the cloud" is just someone else's computer, and someone must operate it by hand before any automation can replace that labor. Students SSH into an ec2-console-managed Ubuntu VM for the first time, learn bare-metal operational skills (filesystem, processes, ports, YAML, curl), and manually deploy `hello-world` — only to kill it and discover why manual operations do not survive. The end state: a student who can operate a remote Linux machine and articulate why that operation needs to be automated by later sessions.

## The machine behind the cloud

The boardroom framing: every AI product demo dies the moment its operator closes the laptop, and companies pay for the machinery and people that make software survive its authors walking away. Concrete numbers anchor this: the oft-cited Gartner average downtime cost is $5,600/minute, and the student's own VM — a `t3.small` this week — costs roughly $0.021/hour, about $15/month if left running continuously, growing to `t3.medium` at Session 4 and `t3.large` at Session 8. With over 100 students, one forgotten machine multiplied across the cohort becomes a real invoice, which is why the stop/destroy discipline is graded every week from here on. A single production incident is framed as routinely consuming 4–8 engineer-hours — the labor cost automation exists to buy back.

## The five things to know cold

SSH is a remote shell over an encrypted channel authenticated by a key pair: the server holds the public key, the student proves identity with the private key, never shared or committed, and the private key file must be `chmod 400`. Filesystem and permissions: `/` is root, `~` is home, `ls -l` shows `rwx` triads for owner/group/others, `chmod +x` makes a file executable, and `chmod 777` is never the correct fix. Processes: every running program has a PID; `ps aux | grep <name>` finds it, `kill <PID>` sends the polite SIGTERM, `kill -9` sends the uncatchable SIGKILL as a last resort, and Ctrl-C sends SIGINT to the foreground job — remote-editor terminals can survive disconnection, so termination must be verified with `ss` and `curl`. Ports: a server listens on a TCP port; `ss -ltn` lists them, and bind address matters — `127.0.0.1:8000` is reachable only from the machine itself while `0.0.0.0:8000` is reachable externally, subject to the security group also allowing the port. YAML and HTTP: YAML uses spaces-only indentation (a tab is a syntax error) and `key: value` with a space after the colon; HTTP verbs (GET reads, POST sends) and status classes (2xx OK, 4xx client error such as 404/405, 5xx server error) are read with `curl -i`.

## The artisanal deploy lab

Each student provisions an Ubuntu 24.04 `t3.small` workspace via the ec2-console S2 Terraform profile, with the controller retaining state, access keys, and a persistent Elastic IP outside the VM — Session 6 later exposes this same Terraform state. Lab Block A is a drill circuit: connecting with `ssh -i dbai.pem ubuntu@<VM_IP>`, orienting with `pwd`/`ls -la`/`cd`, a permissions trap where a fresh `script.sh` fails "Permission denied" until `chmod +x` (an AI suggesting `chmod 777` must be refused), a process drill with `sleep 600 &` found via `ps aux` and killed via `kill`, a ports check with `ss -ltn` showing only sshd on port 22, and a first `curl -i https://ifconfig.me`.

Lab Block B is the artisanal deploy itself: giving the VM its own GitHub SSH identity, cloning the private `hello-world` copy, merging the `starter-s02-v1.0.0` tag with `--allow-unrelated-histories` (template copies have independent Git histories, so this merge is required and must not discard prior `ABOUT.md`/`JOURNAL.md` work), running `uv sync`, and hitting the deliberate YAML trap in `config/settings.yaml` — a tab indent and a missing space after a colon that crash the app, fixed via `nano`. Once running, the app is probed from a second SSH session and the laptop: `GET /` returns 200 with JSON including the server hostname, `/health` returns 200, `/nope` returns 404, POST `/` returns 405, and `/boom` returns 500 with a traceback visible as a live log. The laptop's `curl` to `<VM_IP>:8000` succeeding — while `localhost:8000` would not — proves the two conditions needed: `0.0.0.0` binding and a security group rule allowing port 8000.

## The death drill and its lesson

Ctrl-C kills the foreground app; a second SSH session confirms via `ss -ltn` that port 8000 is gone, and the laptop's `curl` now fails — both screenshotted as evidence. The lesson is the absence of a supervisor or restart policy: nothing brings the process back, and closing a remote editor window is not a reliable way to prove a process stopped, since its terminal can survive disconnection. Students record an "artisanal deploy stopwatch" — minutes and manual steps used — in `JOURNAL.md`, since Session 5's automated deployment is compared directly against this baseline. The debrief maps every student-proposed fix (nohup, tmux, reboot, cron) onto the semester roadmap: containers (S4) package it, pipelines (S5) deploy it, Terraform (S6) makes the machine reproducible, k3s (S8) makes it self-healing.

## Common failure modes and diagnosis

Instructors watch for AI suggesting `chmod 777` as a permissions fix, `pip install`/`python3` instead of `uv sync`/`uv run`, keeping the app alive with `nohup`, `tmux`, or a pasted systemd unit (jumping ahead of the course and hiding the lesson), or "fixing" the YAML trap by converting the file to JSON — any of these in a repo triggers a spot-check. TAs are briefed on three stalls: Windows key permission errors (fixed with `icacls`), invisible tabs in YAML (diagnosed with `cat -A settings.yaml`, showing tabs as `^I`), and incomplete ec2-console profiles (diagnosed with `doctor`, never a second unpinned `uv`).

## Deliverable and assessment seeds

The deliverable is the `s2` branch pushed before midnight: fixed `config/settings.yaml`, `evidence/s2/curl-ok.png`, `evidence/s2/curl-dead.png`, and a journal entry — merged into the student's `main`. The exit ticket asks for the two conditions that had to be true for the laptop's curl to reach the app (bind address and security group). Quiz questions drawn from the know-cold list include `ss -ltn`'s three flags, why a `127.0.0.1`-bound service is unreachable even with the firewall open, `kill` versus `kill -9`, and what `uv sync` guarantees about reproducibility — recurring in fault-injection exam variants such as "the invisible service" (mis-bound `settings.yaml`) and "won't even start" (stripped execute bit plus a re-injected tab).
