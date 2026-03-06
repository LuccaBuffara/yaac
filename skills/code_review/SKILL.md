---
name: code-review
description: Review code for bugs, security issues, performance problems, and readability.
---

# Code Review

## When to use this skill
Use when the user asks for a code review, wants feedback on code quality, or asks if code looks correct.

## Process

1. Read all relevant files before commenting — never review code you haven't seen.
2. Organize feedback into sections:
   - **Bugs / correctness issues** — things that are broken or will break
   - **Security** — vulnerabilities, injection risks, exposed secrets
   - **Performance** — obvious bottlenecks or inefficiencies
   - **Readability** — confusing logic, misleading names, missing context
   - **Suggestions** — optional improvements (clearly marked as non-critical)
3. Be specific: reference file names and line numbers.
4. Be concise: skip praise and filler. Focus on actionable feedback.
5. If the code is clean, say so briefly — don't invent issues.
