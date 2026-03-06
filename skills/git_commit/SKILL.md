---
name: git-commit
description: Create git commits — stage files, write commit messages, verify the result.
---

# Git Commit

## When to use this skill
Use when the user asks to commit changes, stage files, or create a git commit.

## Process

1. Run `git status` to see what files are changed or untracked.
2. Run `git diff` to understand what actually changed.
3. Run `git log --oneline -5` to learn the existing commit message style.
4. Stage only relevant files — never use `git add -A` blindly. Avoid committing `.env`, secrets, or large binaries.
5. Write a concise commit message:
   - First line: short summary in imperative mood (e.g. "add user auth", "fix null pointer in parser")
   - Keep it under 72 characters
   - Add a body only if the change needs extra context
6. Create the commit. Never use `--no-verify` unless the user explicitly asks.
7. Run `git status` again to confirm success.

Never push unless the user explicitly asks.
