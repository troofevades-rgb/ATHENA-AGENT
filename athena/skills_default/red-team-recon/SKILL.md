---
description: Methodical recon-first approach to authorized offensive engagements
name: red-team-recon
created_at: '2026-05-26T00:00:00Z'
last_activity_at: '2026-05-26T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Red Team Recon

Disciplined, recon-heavy approach to authorized offensive engagements
(CTFs, pentests, security research). The premise: most pentest failures
are knowledge failures, not skill failures — you didn't know the target
well enough before you started shooting.

## When to use this skill

Use for an authorized engagement against a target: CTF, sanctioned
pentest, internal red team exercise. Do NOT use against any target
you don't have written authorization for. If unclear, STOP and ask.

## Pre-engagement

Before any tool fires:

- **Scope.** What IPs, domains, hours of operation, data classes are
  in/out of scope? Write it down at the top of your notes.
- **Rules of engagement.** Active exploitation allowed? DoS? Lateral
  movement? Phishing? If you don't know, ask the engagement owner.
- **Evidence pattern.** Where are findings recorded, screenshotted,
  preserved? Set this up before you have findings.

## Recon phases (the 80/20)

### 1. Surface enumeration — what exists?

```
nmap -sV -sC -p- <target>          # full port + service detection
subfinder -d <domain>              # subdomain enumeration
amass enum -passive -d <domain>    # passive OSINT
```

Record: open ports, banners, hostnames, TLS cert subjects. Don't move
on until you have a complete-feeling map.

### 2. Service-level enumeration

For each interesting service from phase 1:

- **HTTP/HTTPS:** ``feroxbuster`` or ``ffuf`` for paths; ``nuclei`` for
  known-vuln templates; manual browser pass for auth flows
- **SMB/AD:** ``netexec smb`` for users, shares, password policy
- **Database ports:** version + default-cred probe
- **Custom:** Wireshark / strings on captured traffic

### 3. Vulnerability hypothesis

You should now have a 3–7 item hypothesis list, each of the form:

> "Service X on port Y looks like it might have weakness Z because
> [observation]. Path to validate: [step]. Path to exploit: [step]."

If you can't write a hypothesis, do more recon — don't start brute-
forcing things.

## Active phase

Validate hypotheses cheapest-first:

1. **Default credentials** (cheap, often works)
2. **Known-CVE PoC** for the exact version observed
3. **Misconfiguration** (open share, exposed config endpoint, SSRF)
4. **Custom exploit** (longest tail — only if 1–3 fail)

After each exploit attempt: re-recon. New access often reveals
internal services the external pass couldn't see.

## Reporting hygiene

- Every finding: repro steps, evidence (screenshot/output), severity,
  remediation suggestion.
- No finding is too small to log — even a low-sev info disclosure helps
  the defender prioritize.
- Always cite the exact command + output. "I ran nmap and found a
  vulnerability" is not a report.
