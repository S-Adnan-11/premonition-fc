# Development

- Use the locked dependencies and the existing Python environment. Avoid dependency changes unless the task needs them.
- Run the relevant tests before committing. For prospective fitting, issuance or settlement changes, run `python -B -m unittest discover -s prospective_tests -v`. Use the historical, iteration and site suites when those areas change.
- Preserve the shared London cutoff, frozen fits, original paired forecasts and fixed settled-fixture review rules. Use fictional inputs for workflow tests.

# Git workflow

- Make small, coherent commits and push tested increments regularly.
- Use a feature branch and a focused pull request when review would help, including changes to these instructions. Leave the merge decision to the maintainer.
- Write concise, natural developer prose in commits, pull requests, review comments and code comments. Keep chat references, assistant narration, internal milestone labels and co-author footers out of public content.

# Data and review

- Keep credentials, provider payloads, datasets, fitted artifacts, private notes, request ledgers, approval records and operational evidence outside Git worktrees.
- Check `.gitignore` before staging. It is a backup to the external-output checks, not a place to store private evidence.
- Stage explicit paths. Inspect the staged file list and full diff before each commit, and review outgoing commits before pushing.
- Check for `.env` files, secrets, private notes, provider responses and operational artifacts. Keep an intentional public `.env.example` free of real values.
- Preserve existing audit evidence and stopped request ledgers. Do not resume provider requests or change their allowance without the task's authorization.
