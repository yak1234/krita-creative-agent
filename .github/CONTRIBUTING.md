# Contributing to Toska

Toska is a fork of Krita with an AI painting agent built in. Issues and pull requests here are about Toska and the
changes this fork makes to Krita.

For bugs that also happen in Krita itself, please report them to the Krita project at https://bugs.kde.org, where a fix
helps every Krita user.

## Before you open a pull request

- Run `agent/ci.sh` and make sure every group passes. It runs the plugin's Python tests, the companion's tests and
  typecheck, and the C++ programs.
- Keep each pull request to one change, with a test that fails without it.
- New companion modules are TypeScript. Plugin code goes through `qt_compat`, so it runs under PyQt5 and PyQt6.

## How changes reach `main`

`main` contains only commits that passed `agent/ci.sh` and the pre-publication check (`agent/prepublish-check.sh`, which
looks for secrets and personal data). The history starts from the Krita commit this fork is based on. Krita's own
history is at https://invent.kde.org/graphics/krita, and Krita's master is merged into the fork about once a month.
