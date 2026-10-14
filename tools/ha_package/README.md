# Development channel: Home Assistant pulls from GitHub

This directory holds the two files that make a Home Assistant instance pull Device
Routines builds by itself (PRD 11.2, TECH_SPEC 10.2). Nothing is ever copied from a laptop
into the configuration directory, and nothing here restarts Home Assistant unless you turn
that on.

| File | Where it goes | What it does |
| --- | --- | --- |
| `../ha_deploy.py` | `/config/tools/ha_deploy.py` | Downloads one commit from GitHub, verifies it, byte compiles it and swaps it into `custom_components/device_routines`. Standard library only. Shared with the sibling project ha-device-links. |
| `device_routines_dev.yaml` | `/config/packages/device_routines_dev.yaml` | A package with the three shell commands, the REST sensor that watches the `dev-stable` tag, the helpers and the three automations of the loop. |

## How the loop works

1. CI runs on every push to `dev`. When every job is green, the `promote` job moves the
   `dev-stable` tag to that commit. A red commit can never be deployed.
2. `sensor.device_routines_dev_stable` polls the GitHub API for that tag every ten minutes
   (six unauthenticated calls an hour).
3. When the sha changes, the automation **Device Routines: deploy dev-stable** runs
   `shell_command.deploy_device_routines`, which prints one JSON object. The automation
   then does exactly one thing:
   - `restart_required`: creates the persistent notification `device_routines_deploy`
     saying which commit is waiting. Python, the manifest, services, strings and
     translations all need a restart.
   - `reload_automations`: calls `automation.reload`. Only the blueprint changed.
   - `browser_reload`: the notification says to reload the browser. Only the console
     bundle changed.
4. A restart is yours to perform, unless the restart window is on (below).
5. After a restart, **Device Routines: post restart check** waits three minutes. If the
   Health sensor is still missing and the deployed commit is newer than the last commit
   that loaded successfully, it runs `shell_command.rollback_device_routines` and leaves a
   notification saying a restart is needed. The tool refuses a second rollback without a
   deploy in between, so this cannot loop. The same automation records the commit of every
   successful load in `input_text.device_routines_last_good_commit`.

## Bootstrap (once)

1. Copy `tools/ha_deploy.py` to `/config/tools/ha_deploy.py`.
2. Copy `device_routines_dev.yaml` to `/config/packages/device_routines_dev.yaml`. If
   `configuration.yaml` does not load packages yet, add
   `homeassistant: packages: !include_dir_named packages`, or merge the sections of the
   file into `configuration.yaml`.
3. Replace `<owner>` in the package with the GitHub user that owns the repository. It
   appears twice: in the deploy shell command and in the REST sensor's resource.
4. Check the configuration and restart Home Assistant.
5. Turn on `input_boolean.device_routines_auto_deploy` and set the two restart window
   times (the defaults suggested by the plan are 03:00 and 04:00). The helpers keep
   their values across restarts, which is why the package does not force them.

After that, `shell_command.deploy_device_routines`, `sensor.device_routines_dev_stable`
and the three automations exist, and the next green push to `dev` reaches the instance on
its own.

## The restart policy

By default nothing restarts Home Assistant: the deploy leaves a notification and stops.
Turning on `input_boolean.device_routines_auto_restart` lets the instance restart itself
in two cases, both at most once per deploy:

- right after a deploy that needs a restart, when the current time is inside the window;
- at the start of the window, when a deploy is still waiting (the deployed commit differs
  from the commit the Health sensor reports).

The switch stays off until you turn it on.

## Deploying and rolling back by hand

The shell commands take no arguments except `ref` on the deploy, so they are usable from
the Developer tools, from scripts and from the Home Assistant MCP server. Every one of them
returns the tool's JSON in `stdout`.

```yaml
# a specific tag, branch or commit instead of dev-stable
action: shell_command.deploy_device_routines
data:
  ref: v0.1.0

# restore the newest backup (needs a restart afterwards, like a deploy)
action: shell_command.rollback_device_routines

# what is deployed, whether HACS manages the install, the backups, whether the code parses
action: shell_command.device_routines_deploy_status
```

Backups live under `/config/.ha_deploy/device_routines/backups/`, five at most. A
rollback consumes the newest one, so a second rollback goes one step further back, but
only after a deploy has happened in between.

## Switching to the HACS channel later

When a release exists, install Device Routines through HACS as a custom repository
(README at the repository root), then turn `input_boolean.device_routines_auto_deploy`
off and remove this package and `/config/tools/ha_deploy.py`. The deploy tool warns in its
output when it finds a HACS managed install, and the Health sensor reports the channel.
