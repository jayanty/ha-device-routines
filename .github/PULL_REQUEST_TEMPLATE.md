## What changed

<!-- One paragraph. Link the issue if there is one. -->

## Checklist

- [ ] Tests ship in this change (a bug fix carries a regression test)
- [ ] `ruff check`, `ruff format --check`, `mypy` and `pytest --cov` pass locally
- [ ] Every new user facing string has a translation key in `strings.json` and `translations/en.json`
- [ ] Docs updated (README, `docs/`, `services.yaml`)
- [ ] `CHANGELOG.md` updated under Unreleased
- [ ] `quality_scale.yaml` reviewed if behavior changed
- [ ] No data from a real home: no entity ids, device, area or person names, hosts or tokens
- [ ] No em dash character in any added text
- [ ] Conventional commit messages
