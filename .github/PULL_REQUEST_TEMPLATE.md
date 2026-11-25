Describe the change and why. One paragraph is enough.

If you touched the interface, attach the screenshots from
`node tests/_shots.cjs <url>`, and the audit output from
`node tests/_audit.cjs <url>` when colour, type size or spacing changed.

The checks I will run on this branch:

    python tools/ci-run.py
    python -m mypy
    python tools/check-secrets.py

- [ ] `python tools/ci-run.py` passes, summary pasted below
- [ ] `python -m mypy` is clean
- [ ] No token, API key, tailnet hostname or personal path in the diff
- [ ] The app still imports only the standard library
- [ ] New animation is behind `prefers-reduced-motion`
- [ ] Docs updated where behaviour changed

<details>
<summary>ci-run.py output</summary>

```

```

</details>
