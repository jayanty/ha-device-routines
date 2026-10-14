# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Privacy tooling: `tools/privacy_check.py` (pre commit hook on staged content and the
  commit message, generic patterns in CI), `tools/make_denylist.py` (builds the private
  denylist from a registries capture), `tools/anonymize.py` (turns raw captures into
  fixtures with stable generic stand ins) and `tools/style_check.py` (refuses the em dash
  character), each with unit tests.
- Repository skeleton: tooling configuration (ruff with every rule on, mypy strict,
  pytest with the Home Assistant test harness pinned to core 2026.10.1, coverage gate at
  95 percent), the MIT license, HACS metadata, issue and pull request templates,
  Dependabot, placeholder brand images and the decisions log.
